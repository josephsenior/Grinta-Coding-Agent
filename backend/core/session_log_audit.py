"""Generate stripped session logs and audit reports from ``app.log``."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

NOISE_PATTERNS = (
    re.compile(r'on_event received StreamingChunkAction\b'),
    re.compile(r'\[streaming-dbg\]'),
    re.compile(r'\[TUI\] _dispatch_to_agent: poll #'),
    re.compile(r'_dispatch_to_agent: \d+ consecutive polls'),
    re.compile(r'dispatching via run_or_schedule$'),
)

ISSUE_LEVELS = frozenset({'WARNING', 'ERROR', 'CRITICAL'})

ISSUE_MSG_PATTERNS = (
    re.compile(r'pending action timed out', re.I),
    re.compile(r'HARD TIMEOUT', re.I),
    re.compile(r'AGENT_HARD_TIMEOUT', re.I),
    re.compile(r'STALL TIMEOUT', re.I),
    re.compile(r'stuck_detection', re.I),
    re.compile(r'recover|retry|backoff', re.I),
    re.compile(r'exception|traceback|failed', re.I),
    re.compile(r'dropped while the renderer was backlogged', re.I),
    re.compile(r'Memory pressure', re.I),
    re.compile(r'circuit.?breaker', re.I),
    re.compile(r'no.step.progress', re.I),
)

STATE_RE = re.compile(
    r'Setting agent\([^)]+\) state from AgentState\.(\w+) to AgentState\.(\w+)'
)
ACTION_RE = re.compile(r'obtained action=ActionType\.(\w+)')
LLM_DONE_RE = re.compile(r'OrchestratorExecutor\.async_execute done in ([\d.]+)s')
FILE_EVENT_RE = re.compile(r'(FileWrite|FileEdit|FileRead)(Action|Observation)')


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
        if 'T' in raw:
            return datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return datetime.strptime(raw.split(',')[0], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def is_noise(message: str) -> bool:
    return any(p.search(message) for p in NOISE_PATTERNS)


def is_issue(level: str, message: str) -> bool:
    if level in ISSUE_LEVELS:
        return True
    return any(p.search(message) for p in ISSUE_MSG_PATTERNS)


def format_line(obj: dict) -> str:
    ts = obj.get('asctime') or obj.get('timestamp') or ''
    level = obj.get('level', 'INFO')
    msg = obj.get('message', '')
    extra = []
    for key in ('msg_type', 'conversation_id'):
        if key in obj and key != 'message':
            extra.append(f'{key}={obj[key]}')
    suffix = f' [{", ".join(extra)}]' if extra else ''
    return f'{ts} [{level}] {msg}{suffix}'


@dataclass
class _AuditAccumulator:
    total: int = 0
    kept: int = 0
    stripped: int = 0
    levels: Counter[str] = field(default_factory=Counter)
    issue_lines: list[str] = field(default_factory=list)
    state_transitions: list[tuple[str, str, str, int]] = field(default_factory=list)
    actions: list[tuple[str, str, int]] = field(default_factory=list)
    llm_calls: list[tuple[float, str, int]] = field(default_factory=list)
    file_events: list[tuple[str, str, int]] = field(default_factory=list)
    end_state: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    pending_timeouts: int = 0
    retries: int = 0
    on_event_types: Counter[str] = field(default_factory=Counter)


def _update_timestamps(acc: _AuditAccumulator, obj: dict) -> None:
    ts = parse_ts(obj.get('timestamp') or obj.get('asctime'))
    if ts:
        acc.first_ts = acc.first_ts or ts
        acc.last_ts = ts


def _extract_state_transition(msg: str, line_no: int, acc: _AuditAccumulator) -> None:
    m = STATE_RE.search(msg)
    if m:
        acc.state_transitions.append((m.group(1), m.group(2), msg, line_no))
        acc.end_state = m.group(2)


def _extract_action(msg: str, line_no: int, acc: _AuditAccumulator) -> None:
    m = ACTION_RE.search(msg)
    if m:
        acc.actions.append((m.group(1), msg, line_no))


def _extract_llm_call(msg: str, line_no: int, acc: _AuditAccumulator) -> None:
    m = LLM_DONE_RE.search(msg)
    if m:
        acc.llm_calls.append((float(m.group(1)), msg, line_no))


def _extract_file_event(msg: str, line_no: int, acc: _AuditAccumulator) -> None:
    m = FILE_EVENT_RE.search(msg)
    if m:
        acc.file_events.append((m.group(1) + m.group(2), msg[:120], line_no))


def _extract_on_event_type(msg: str, acc: _AuditAccumulator) -> None:
    if 'on_event received ' in msg and 'StreamingChunkAction' not in msg:
        evt = msg.split('on_event received ', 1)[-1].split(' (id=', 1)[0]
        acc.on_event_types[evt] += 1


def _extract_health_signals(msg: str, acc: _AuditAccumulator) -> None:
    if re.search(r'pending action timed out', msg, re.I):
        acc.pending_timeouts += 1
    if re.search(r'\bretry\b|\bbackoff\b|recover', msg, re.I):
        acc.retries += 1


def _process_log_line(
    line_no: int,
    line: str,
    acc: _AuditAccumulator,
    out,
) -> None:
    acc.total += 1
    line = line.strip()
    if not line:
        return
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        out.write(f'# L{line_no} (non-json) {line}\n')
        acc.kept += 1
        return

    msg = obj.get('message', '')
    level = obj.get('level', 'INFO')
    acc.levels[level] += 1

    _update_timestamps(acc, obj)

    if is_noise(msg):
        acc.stripped += 1
        return

    acc.kept += 1
    out.write(format_line(obj) + '\n')

    if is_issue(level, msg):
        acc.issue_lines.append(f'L{line_no}: {format_line(obj)}')

    _extract_state_transition(msg, line_no, acc)
    _extract_action(msg, line_no, acc)
    _extract_llm_call(msg, line_no, acc)
    _extract_file_event(msg, line_no, acc)
    _extract_on_event_type(msg, acc)
    _extract_health_signals(msg, acc)


def _compute_duration(acc: _AuditAccumulator) -> float:
    if acc.first_ts and acc.last_ts:
        return (acc.last_ts - acc.first_ts).total_seconds() / 60.0
    return 0.0


def _extract_llm_stats(
    acc: _AuditAccumulator,
) -> tuple[list[float], list[tuple[float, int, str]]]:
    llm_times = [t for t, _, _ in acc.llm_calls]
    slow_llm = [(t, ln, m) for t, m, ln in acc.llm_calls if t >= 60.0]
    return llm_times, slow_llm


def _find_suspicious_states(
    acc: _AuditAccumulator,
) -> list[tuple[str, str, str, int]]:
    return [
        (a, b, m, ln)
        for a, b, m, ln in acc.state_transitions
        if b in {'ERROR', 'STOPPED'} or (a == 'ERROR' and b != 'AWAITING_USER_INPUT')
    ]


def _assess_end_state(
    acc: _AuditAccumulator, verdict: str, notes: list[str]
) -> tuple[str, list[str]]:
    if acc.end_state == 'FINISHED':
        notes.append('Session ended in FINISHED (success).')
    elif acc.end_state == 'AWAITING_USER_INPUT':
        notes.append('Session ended awaiting user input (normal idle).')
    elif acc.end_state in {'ERROR', 'STOPPED'}:
        verdict = 'ISSUES FOUND'
        notes.append(f'Session ended in {acc.end_state}.')
    return verdict, notes


def _assess_health_signals(
    acc: _AuditAccumulator,
    suspicious_states: list,
    verdict: str,
    notes: list[str],
) -> tuple[str, list[str]]:
    if acc.pending_timeouts:
        verdict = 'ISSUES FOUND'
        notes.append(f'{acc.pending_timeouts} pending-action timeout(s) detected.')
    if suspicious_states:
        verdict = 'ISSUES FOUND'
        notes.append(f'{len(suspicious_states)} error/stop state transition(s).')
    return verdict, notes


def _assess_log_levels(
    acc: _AuditAccumulator, verdict: str, notes: list[str]
) -> tuple[str, list[str]]:
    warn_count = acc.levels.get('WARNING', 0)
    err_count = acc.levels.get('ERROR', 0) + acc.levels.get('CRITICAL', 0)
    if err_count:
        verdict = 'ISSUES FOUND'
        notes.append(f'{err_count} ERROR/CRITICAL log line(s).')
    elif warn_count and warn_count <= 5:
        notes.append(f'{warn_count} WARNING(s) — review below (may be benign).')
    elif warn_count:
        verdict = 'REVIEW'
        notes.append(f'{warn_count} WARNING(s) — worth scanned.')
    return verdict, notes


def _compute_verdict(
    acc: _AuditAccumulator,
) -> tuple[
    str,
    list[str],
    float,
    list[float],
    list[tuple[float, int, str]],
    list[tuple[str, str, str, int]],
]:
    duration_min = _compute_duration(acc)
    llm_times, slow_llm = _extract_llm_stats(acc)
    suspicious_states = _find_suspicious_states(acc)
    verdict = 'CLEAN'
    notes: list[str] = []
    verdict, notes = _assess_end_state(acc, verdict, notes)
    verdict, notes = _assess_health_signals(acc, suspicious_states, verdict, notes)
    verdict, notes = _assess_log_levels(acc, verdict, notes)
    return verdict, notes, duration_min, llm_times, slow_llm, suspicious_states


def _write_report_header(
    rep, acc: _AuditAccumulator, log_path: Path, stripped_path: Path
) -> None:
    rep.write('SESSION LOG AUDIT\n')
    rep.write('=' * 72 + '\n')
    rep.write(f'Source: {log_path}\n')
    rep.write(f'Stripped log: {stripped_path}\n')
    rep.write(f'Total lines: {acc.total:,}\n')
    rep.write(
        f'Stripped (noise): {acc.stripped:,} ({100 * acc.stripped / max(acc.total, 1):.1f}%)\n'
    )
    rep.write(f'Kept lines: {acc.kept:,}\n')
    if acc.first_ts and acc.last_ts:
        duration_min = (acc.last_ts - acc.first_ts).total_seconds() / 60.0
        rep.write(
            f'Duration: {duration_min:.1f} min '
            f'({acc.first_ts.isoformat()} -> {acc.last_ts.isoformat()})\n'
        )
    rep.write(f'Final agent state: {acc.end_state or "unknown"}\n')
    rep.write('\n')


def _write_report_level_counts(rep, acc: _AuditAccumulator) -> None:
    rep.write('LEVEL COUNTS (all lines)\n')
    rep.write('-' * 40 + '\n')
    for lvl, cnt in acc.levels.most_common():
        rep.write(f'  {lvl}: {cnt:,}\n')
    rep.write('\n')


def _write_report_health_signals(rep, acc: _AuditAccumulator, llm_times: list) -> None:
    rep.write('HEALTH SIGNALS\n')
    rep.write('-' * 40 + '\n')
    rep.write(f'  Pending action timeouts: {acc.pending_timeouts}\n')
    rep.write(f'  Retry/recovery mentions: {acc.retries}\n')
    rep.write(f'  LLM calls completed: {len(acc.llm_calls)}\n')
    if llm_times:
        rep.write(
            f'  LLM latency — min={min(llm_times):.1f}s '
            f'median={sorted(llm_times)[len(llm_times) // 2]:.1f}s '
            f'max={max(llm_times):.1f}s\n'
        )
    rep.write(f'  File operations logged: {len(acc.file_events)}\n')
    rep.write(f'  Agent actions obtained: {len(acc.actions)}\n')
    rep.write('\n')


def _write_report_verdict(rep, verdict: str, notes: list[str]) -> None:
    rep.write(f'VERDICT: {verdict}\n')
    for note in notes:
        rep.write(f'  • {note}\n')
    rep.write('\n')


def _write_report_issues(rep, acc: _AuditAccumulator) -> None:
    if not acc.issue_lines:
        return
    rep.write(f'ISSUES / WARNINGS ({len(acc.issue_lines)} lines)\n')
    rep.write('-' * 40 + '\n')
    for item in acc.issue_lines[:200]:
        rep.write(item + '\n')
    if len(acc.issue_lines) > 200:
        rep.write(f'... and {len(acc.issue_lines) - 200} more\n')
    rep.write('\n')


def _write_report_suspicious_states(rep, suspicious_states: list) -> None:
    if not suspicious_states:
        return
    rep.write('SUSPICIOUS STATE TRANSITIONS\n')
    rep.write('-' * 40 + '\n')
    for a, b, m, ln in suspicious_states:
        rep.write(f'L{ln}: {a} -> {b}\n')
    rep.write('\n')


def _write_report_slow_llm(rep, slow_llm: list) -> None:
    if not slow_llm:
        return
    rep.write(f'SLOW LLM CALLS (>=60s) — {len(slow_llm)}\n')
    rep.write('-' * 40 + '\n')
    for t, ln, m in sorted(slow_llm, reverse=True)[:30]:
        rep.write(f'L{ln}: {t:.1f}s\n')
    rep.write('\n')


def _write_report_state_timeline(rep, acc: _AuditAccumulator) -> None:
    rep.write('STATE TRANSITION TIMELINE (deduped consecutive)\n')
    rep.write('-' * 40 + '\n')
    last_pair = None
    for a, b, _, ln in acc.state_transitions:
        pair = (a, b)
        if pair != last_pair:
            rep.write(f'L{ln}: {a} -> {b}\n')
            last_pair = pair
    rep.write('\n')


def _write_report_event_types(rep, acc: _AuditAccumulator) -> None:
    rep.write('TOP NON-CHUNK EVENT TYPES\n')
    rep.write('-' * 40 + '\n')
    for evt, cnt in acc.on_event_types.most_common(25):
        rep.write(f'  {cnt:5d}  {evt}\n')
    rep.write('\n')


def _write_report_action_breakdown(rep, acc: _AuditAccumulator) -> None:
    rep.write('ACTION TYPE BREAKDOWN\n')
    rep.write('-' * 40 + '\n')
    action_counts = Counter(a for a, _, _ in acc.actions)
    for act, cnt in action_counts.most_common():
        rep.write(f'  {cnt:4d}  {act}\n')
    rep.write('\n')


def _write_report_file_events(rep, acc: _AuditAccumulator) -> None:
    if not acc.file_events:
        return
    rep.write(f'FILE EVENTS (first 40 of {len(acc.file_events)})\n')
    rep.write('-' * 40 + '\n')
    for kind, msg, ln in acc.file_events[:40]:
        rep.write(f'L{ln} [{kind}] {msg}\n')
    rep.write('\n')


def _write_report(
    rep,
    acc: _AuditAccumulator,
    log_path: Path,
    stripped_path: Path,
    verdict: str,
    notes: list[str],
    llm_times: list,
    slow_llm: list,
    suspicious_states: list,
) -> None:
    _write_report_header(rep, acc, log_path, stripped_path)
    _write_report_level_counts(rep, acc)
    _write_report_health_signals(rep, acc, llm_times)
    _write_report_verdict(rep, verdict, notes)
    _write_report_issues(rep, acc)
    _write_report_suspicious_states(rep, suspicious_states)
    _write_report_slow_llm(rep, slow_llm)
    _write_report_state_timeline(rep, acc)
    _write_report_event_types(rep, acc)
    _write_report_action_breakdown(rep, acc)
    _write_report_file_events(rep, acc)


def analyze_session(
    log_path: Path,
    stripped_path: Path,
    report_path: Path,
) -> SessionAuditResult:
    acc = _AuditAccumulator()

    with (
        log_path.open(encoding='utf-8', errors='replace') as src,
        stripped_path.open('w', encoding='utf-8') as out,
    ):
        for line_no, line in enumerate(src, 1):
            _process_log_line(line_no, line, acc, out)

    verdict, notes, duration_min, llm_times, slow_llm, suspicious_states = (
        _compute_verdict(acc)
    )

    with report_path.open('w', encoding='utf-8') as rep:
        _write_report(
            rep,
            acc,
            log_path,
            stripped_path,
            verdict,
            notes,
            llm_times,
            slow_llm,
            suspicious_states,
        )

    return SessionAuditResult(
        log_path=log_path,
        stripped_path=stripped_path,
        report_path=report_path,
        total_lines=acc.total,
        kept_lines=acc.kept,
        stripped_lines=acc.stripped,
        verdict=verdict,
    )


def generate_session_audit_artifacts(
    log_dir: str | Path,
    *,
    log_name: str = 'app.log',
) -> SessionAuditResult | None:
    """Write ``app.stripped.log`` and ``app.audit.txt`` beside ``app.log``."""
    if not session_audit_enabled():
        return None

    directory = Path(log_dir)
    log_path = directory / log_name
    if not log_path.is_file():
        return None
    if log_path.stat().st_size <= 0:
        return None

    stem = log_path.stem
    stripped_path = directory / f'{stem}.stripped.log'
    report_path = directory / f'{stem}.audit.txt'
    return analyze_session(log_path, stripped_path, report_path)


__all__ = [
    'SessionAuditResult',
    'analyze_session',
    'generate_session_audit_artifacts',
    'session_audit_enabled',
]
