"""Generate session.audit.txt and session.txt from ``session.jsonl``."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.logging.session_event_logger import (
    AUDIT_FILENAME,
    SESSION_LOG_FILENAME,
    TRANSCRIPT_FILENAME,
)
from backend.core.logging.session_log_renderer import write_session_transcript

ISSUE_LEVELS = frozenset({'WARNING', 'ERROR', 'CRITICAL'})


@dataclass(frozen=True)
class SessionAuditResult:
    log_path: Path
    stripped_path: Path
    report_path: Path
    total_lines: int
    kept_lines: int
    stripped_lines: int
    verdict: str


def session_audit_enabled() -> bool:
    raw = os.getenv('GRINTA_SESSION_AUDIT', 'true').strip().lower()
    return raw not in {'0', 'false', 'no', 'off'}


def parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return None


@dataclass
class _AuditAccumulator:
    total: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    levels: Counter[str] = field(default_factory=Counter)
    event_types: Counter[str] = field(default_factory=Counter)
    issue_lines: list[str] = field(default_factory=list)
    state_transitions: list[tuple[str, str, int]] = field(default_factory=list)
    llm_latencies_ms: list[int] = field(default_factory=list)
    file_events: list[tuple[str, str, int]] = field(default_factory=list)
    tool_outcomes: Counter[str] = field(default_factory=Counter)
    end_state: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    pending_timeouts: int = 0
    retries: int = 0
    by_model: Counter[str] = field(default_factory=Counter)
    by_mode: Counter[str] = field(default_factory=Counter)
    by_autonomy: Counter[str] = field(default_factory=Counter)
    issues_by_model: Counter[str] = field(default_factory=Counter)
    tool_fail_by_model: Counter[str] = field(default_factory=Counter)
    first_issue_ctx: dict[str, Any] | None = None
    runtime_msg_types: Counter[str] = field(default_factory=Counter)
    last_known_model: str | None = None
    compaction_fallbacks: int = 0


def _ctx_model(record: dict[str, Any]) -> str:
    ctx = record.get('ctx')
    if isinstance(ctx, dict):
        return str(ctx.get('model') or 'unknown')
    return 'unknown'


def _ctx_mode(record: dict[str, Any]) -> str:
    ctx = record.get('ctx')
    if isinstance(ctx, dict):
        return str(ctx.get('active_run_mode') or ctx.get('mode') or 'unknown')
    return 'unknown'


def _ctx_autonomy(record: dict[str, Any]) -> str:
    ctx = record.get('ctx')
    if isinstance(ctx, dict):
        return str(ctx.get('autonomy') or 'unknown')
    return 'unknown'


def _process_event(
    line_no: int, record: dict[str, Any], acc: _AuditAccumulator
) -> None:
    acc.total += 1
    acc.events.append(record)
    level = str(record.get('level', 'INFO'))
    acc.levels[level] += 1
    event = str(record.get('event', 'UNKNOWN'))
    acc.event_types[event] += 1

    ts = parse_ts(record.get('ts'))
    if ts:
        acc.first_ts = acc.first_ts or ts
        acc.last_ts = ts

    model = _ctx_model(record)
    if model == 'unknown':
        model = acc.last_known_model or 'unknown'
    else:
        acc.last_known_model = model
    mode = _ctx_mode(record)
    autonomy = _ctx_autonomy(record)
    acc.by_model[model] += 1
    acc.by_mode[mode] += 1
    acc.by_autonomy[autonomy] += 1

    payload = record.get('payload')
    if not isinstance(payload, dict):
        payload = {}

    if event == 'STATE_CHANGE':
        a, b = payload.get('from'), payload.get('to')
        if a and b:
            acc.state_transitions.append((str(a), str(b), line_no))
            acc.end_state = str(b)

    if event == 'TOOL_RESULT':
        ok = payload.get('ok')
        if ok is True:
            acc.tool_outcomes['ok'] += 1
        elif ok is False:
            acc.tool_outcomes['fail'] += 1
            acc.tool_fail_by_model[model] += 1

    if event in {'WIRE_RESPONSE', 'AGENT_STEP'}:
        lat = payload.get('latency_ms')
        if isinstance(lat, (int, float)):
            acc.llm_latencies_ms.append(int(lat))

    if event == 'FILE_EVENT':
        kind = str(payload.get('kind', 'FILE'))
        path_preview = str(payload.get('path', ''))[:120]
        acc.file_events.append((kind, path_preview, line_no))

    if event == 'COMPACTION' and payload.get('kind') == 'summary_fallback':
        acc.compaction_fallbacks += 1

    if event in {'ISSUE', 'RUNTIME'}:
        msg = str(payload.get('message', ''))
        msg_type = payload.get('msg_type')
        if msg_type:
            acc.runtime_msg_types[str(msg_type)] += 1
        if re.search(r'pending action timed out', msg, re.I):
            acc.pending_timeouts += 1
        if re.search(r'\bretry\b|\bbackoff\b|recover', msg, re.I):
            acc.retries += 1

    if event == 'ISSUE' or level in ISSUE_LEVELS:
        acc.issue_lines.append(
            f'L{line_no}: [{event}] {payload.get("message", payload)}'
        )
        acc.issues_by_model[model] += 1
        if acc.first_issue_ctx is None and isinstance(record.get('ctx'), dict):
            acc.first_issue_ctx = dict(record['ctx'])


def _compute_verdict(acc: _AuditAccumulator) -> tuple[str, list[str]]:
    verdict = 'CLEAN'
    notes: list[str] = []

    if acc.end_state == 'FINISHED':
        notes.append('Session ended in FINISHED (success).')
    elif acc.end_state == 'AWAITING_USER_INPUT':
        notes.append('Session ended awaiting user input (normal idle).')
    elif acc.end_state in {'ERROR', 'STOPPED'}:
        verdict = 'ISSUES FOUND'
        notes.append(f'Session ended in {acc.end_state}.')

    if acc.pending_timeouts:
        verdict = 'ISSUES FOUND'
        notes.append(f'{acc.pending_timeouts} pending-action timeout(s) detected.')

    suspicious = [
        (a, b, ln) for a, b, ln in acc.state_transitions if b in {'ERROR', 'STOPPED'}
    ]
    if suspicious:
        verdict = 'ISSUES FOUND'
        notes.append(f'{len(suspicious)} error/stop state transition(s).')

    err_count = acc.levels.get('ERROR', 0) + acc.levels.get('CRITICAL', 0)
    if err_count:
        verdict = 'ISSUES FOUND'
        notes.append(f'{err_count} ERROR/CRITICAL event(s).')
    elif acc.levels.get('WARNING', 0) > 5:
        verdict = 'REVIEW'
        notes.append(f'{acc.levels.get("WARNING", 0)} WARNING(s) — worth scanning.')

    if acc.compaction_fallbacks:
        if verdict == 'CLEAN':
            verdict = 'REVIEW'
        notes.append(
            f'{acc.compaction_fallbacks} compaction summary fallback(s) — '
            'structured memory may have been lost.'
        )

    return verdict, notes


def _write_metadata_breakdowns(rep, acc: _AuditAccumulator) -> None:
    rep.write('METADATA BREAKDOWN\n')
    rep.write('-' * 40 + '\n')
    rep.write('By model:\n')
    for key, cnt in acc.by_model.most_common(10):
        rep.write(f'  {cnt:5d}  {key}\n')
    rep.write('By mode:\n')
    for key, cnt in acc.by_mode.most_common(10):
        rep.write(f'  {cnt:5d}  {key}\n')
    rep.write('By autonomy:\n')
    for key, cnt in acc.by_autonomy.most_common(10):
        rep.write(f'  {cnt:5d}  {key}\n')
    if acc.issues_by_model:
        rep.write('Issues by model:\n')
        for key, cnt in acc.issues_by_model.most_common(10):
            rep.write(f'  {cnt:5d}  {key}\n')
    if acc.tool_fail_by_model:
        rep.write('Tool failures by model:\n')
        for key, cnt in acc.tool_fail_by_model.most_common(10):
            rep.write(f'  {cnt:5d}  {key}\n')
    rep.write('\n')


def _write_report(
    acc: _AuditAccumulator,
    log_path: Path,
    transcript_path: Path,
    verdict: str,
    notes: list[str],
) -> str:
    lines: list[str] = []
    w = lines.append
    w('SESSION LOG AUDIT')
    w('=' * 72)
    w(f'Source: {log_path}')
    w(f'Transcript: {transcript_path}')
    w(f'Total events: {acc.total:,}')
    if acc.first_ts and acc.last_ts:
        duration = (acc.last_ts - acc.first_ts).total_seconds() / 60.0
        w(
            f'Duration: {duration:.1f} min '
            f'({acc.first_ts.isoformat()} -> {acc.last_ts.isoformat()})'
        )
    w(f'Final agent state: {acc.end_state or "unknown"}')
    w('')
    w('LEVEL COUNTS')
    w('-' * 40)
    for lvl, cnt in acc.levels.most_common():
        w(f'  {lvl}: {cnt:,}')
    w('')
    w('HEALTH SIGNALS')
    w('-' * 40)
    w(f'  Pending action timeouts: {acc.pending_timeouts}')
    w(f'  Retry/recovery mentions: {acc.retries}')
    w(
        f'  LLM steps (wire/agent): {acc.event_types.get("WIRE_RESPONSE", 0) + acc.event_types.get("AGENT_STEP", 0)}'
    )
    if acc.llm_latencies_ms:
        sorted_lat = sorted(acc.llm_latencies_ms)
        w(
            f'  LLM latency ms — min={min(sorted_lat)} '
            f'median={sorted_lat[len(sorted_lat) // 2]} '
            f'max={max(sorted_lat)}'
        )
    w(f'  File events: {len(acc.file_events)}')
    if acc.compaction_fallbacks:
        w(f'  Compaction summary fallbacks: {acc.compaction_fallbacks}')
    if acc.tool_outcomes:
        w(
            f'  Tool outcomes: ok={acc.tool_outcomes.get("ok", 0)} '
            f'fail={acc.tool_outcomes.get("fail", 0)}'
        )
    w('')
    w(f'VERDICT: {verdict}')
    for note in notes:
        w(f'  • {note}')
    w('')
    if acc.first_issue_ctx:
        w('CONFIG AT FIRST ISSUE')
        w('-' * 40)
        w(json.dumps(acc.first_issue_ctx, indent=2, default=str))
        w('')
    if acc.issue_lines:
        w(f'ISSUES / WARNINGS ({len(acc.issue_lines)} lines)')
        w('-' * 40)
        for item in acc.issue_lines[:200]:
            w(item)
        if len(acc.issue_lines) > 200:
            w(f'... and {len(acc.issue_lines) - 200} more')
        w('')
    w('EVENT TYPE BREAKDOWN')
    w('-' * 40)
    for evt, cnt in acc.event_types.most_common(40):
        w(f'  {cnt:5d}  {evt}')
    w('')
    if acc.runtime_msg_types:
        w('RUNTIME MSG_TYPE BREAKDOWN')
        w('-' * 40)
        for mt, cnt in acc.runtime_msg_types.most_common(40):
            w(f'  {cnt:5d}  {mt}')
        w('')
    if acc.state_transitions:
        w('STATE TRANSITION TIMELINE')
        w('-' * 40)
        last = None
        for a, b, ln in acc.state_transitions:
            pair = (a, b)
            if pair != last:
                w(f'L{ln}: {a} -> {b}')
                last = pair
        w('')
    _write_metadata_breakdowns_to_lines(lines, acc)
    if acc.file_events:
        w(f'FILE EVENTS (first 40 of {len(acc.file_events)})')
        w('-' * 40)
        for kind, msg, ln in acc.file_events[:40]:
            w(f'L{ln} [{kind}] {msg}')
        w('')
    return '\n'.join(lines)


def _write_metadata_breakdowns_to_lines(
    lines: list[str], acc: _AuditAccumulator
) -> None:
    lines.append('METADATA BREAKDOWN')
    lines.append('-' * 40)
    lines.append('By model:')
    for key, cnt in acc.by_model.most_common(10):
        lines.append(f'  {cnt:5d}  {key}')
    lines.append('By mode:')
    for key, cnt in acc.by_mode.most_common(10):
        lines.append(f'  {cnt:5d}  {key}')
    lines.append('By autonomy:')
    for key, cnt in acc.by_autonomy.most_common(10):
        lines.append(f'  {cnt:5d}  {key}')
    if acc.issues_by_model:
        lines.append('Issues by model:')
        for key, cnt in acc.issues_by_model.most_common(10):
            lines.append(f'  {cnt:5d}  {key}')
    if acc.tool_fail_by_model:
        lines.append('Tool failures by model:')
        for key, cnt in acc.tool_fail_by_model.most_common(10):
            lines.append(f'  {cnt:5d}  {key}')
    lines.append('')


def load_session_events(log_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not log_path.is_file():
        return events
    with log_path.open(encoding='utf-8', errors='replace') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events


def analyze_session(
    log_path: Path,
    transcript_path: Path,
    report_path: Path,
) -> SessionAuditResult:
    acc = _AuditAccumulator()
    events = load_session_events(log_path)
    for line_no, record in enumerate(events, 1):
        _process_event(line_no, record, acc)

    if acc.compaction_fallbacks == 0:
        acc.compaction_fallbacks = sum(
            1 for line in acc.issue_lines if 'Failed to parse summary tool call' in line
        )

    verdict, notes = _compute_verdict(acc)
    write_session_transcript(events, transcript_path)
    report_path.write_text(
        _write_report(acc, log_path, transcript_path, verdict, notes),
        encoding='utf-8',
    )

    return SessionAuditResult(
        log_path=log_path,
        stripped_path=transcript_path,
        report_path=report_path,
        total_lines=acc.total,
        kept_lines=acc.total,
        stripped_lines=0,
        verdict=verdict,
    )


def generate_session_audit_artifacts(
    log_dir: str | Path,
    *,
    log_name: str = SESSION_LOG_FILENAME,
) -> SessionAuditResult | None:
    if not session_audit_enabled():
        return None
    directory = Path(log_dir)
    log_path = directory / log_name
    if not log_path.is_file() or log_path.stat().st_size <= 0:
        return None
    transcript_path = directory / TRANSCRIPT_FILENAME
    report_path = directory / AUDIT_FILENAME
    return analyze_session(log_path, transcript_path, report_path)


__all__ = [
    'SessionAuditResult',
    'analyze_session',
    'generate_session_audit_artifacts',
    'load_session_events',
    'session_audit_enabled',
]
