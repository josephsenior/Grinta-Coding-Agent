"""Tests for session log audit artifact generation from session.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from backend.core.logging.session_log_audit import (
    analyze_session,
    generate_session_audit_artifacts,
)


def _write_event(path: Path, **fields: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'ts': '2026-06-08T10:00:00.000Z',
        'level': 'INFO',
        'event': 'RUNTIME',
        'session_id': 'sess1',
        'workspace': 'ws1',
        'ctx': {'model': 'test/model', 'mode': 'agent', 'autonomy': 'balanced'},
        'payload': {'message': 'hello'},
    }
    record.update(fields)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record) + '\n')


def test_generate_session_audit_artifacts_writes_transcript_and_report(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv('GRINTA_SESSION_AUDIT', 'true')
    log_path = tmp_path / 'session.jsonl'
    _write_event(
        log_path,
        event='RUNTIME',
        payload={'message': 'on_event received StreamingChunkAction (id=1)'},
    )
    _write_event(
        log_path,
        event='STATE_CHANGE',
        payload={'from': 'running', 'to': 'finished'},
    )
    _write_event(
        log_path,
        level='WARNING',
        event='ISSUE',
        payload={'message': 'Memory pressure WARNING (RSS=900 MB)'},
    )

    result = generate_session_audit_artifacts(tmp_path)

    assert result is not None
    assert result.kept_lines == 3
    assert (tmp_path / 'session.txt').exists()
    assert (tmp_path / 'session.audit.txt').exists()
    report = (tmp_path / 'session.audit.txt').read_text(encoding='utf-8')
    assert 'VERDICT:' in report
    assert 'finished' in report.lower() or 'STATE' in report


def test_analyze_session_respects_disable_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('GRINTA_SESSION_AUDIT', 'false')
    log_path = tmp_path / 'session.jsonl'
    _write_event(log_path)

    assert generate_session_audit_artifacts(tmp_path) is None


def test_analyze_session_direct_paths(tmp_path: Path) -> None:
    log_path = tmp_path / 'session.jsonl'
    transcript_path = tmp_path / 'session.txt'
    report_path = tmp_path / 'session.audit.txt'
    _write_event(
        log_path,
        level='ERROR',
        event='ISSUE',
        payload={'message': 'pending action timed out after 120s'},
    )

    result = analyze_session(log_path, transcript_path, report_path)

    assert result.verdict == 'ISSUES FOUND'
    assert 'pending action timed out' in report_path.read_text(encoding='utf-8')


def test_analyze_session_aggregates_event_and_metadata_breakdowns(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / 'session.jsonl'
    transcript_path = tmp_path / 'session.txt'
    report_path = tmp_path / 'session.audit.txt'
    events = [
        {
            'ts': '2026-06-08T10:00:00.000Z',
            'level': 'INFO',
            'event': 'TOOL_RESULT',
            'ctx': {'model': 'm1', 'mode': 'agent', 'autonomy': 'balanced'},
            'payload': {
                'tool': 'create',
                'ok': True,
                'latency_ms': 120,
            },
        },
        {
            'ts': '2026-06-08T10:00:01.000Z',
            'level': 'INFO',
            'event': 'WIRE_RESPONSE',
            'ctx': {'model': 'm1', 'mode': 'agent', 'autonomy': 'balanced'},
            'payload': {'latency_ms': 4500, 'content': 'done'},
        },
        {
            'ts': '2026-06-08T10:00:02.000Z',
            'level': 'WARNING',
            'event': 'ISSUE',
            'ctx': {'model': 'm1', 'mode': 'agent', 'autonomy': 'balanced'},
            'payload': {
                'message': 'drain_step_barrier timed out after 2.0s',
                'msg_type': 'DRAIN_STEP_BARRIER_TIMEOUT',
            },
        },
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('w', encoding='utf-8') as handle:
        for obj in events:
            handle.write(json.dumps(obj) + '\n')

    analyze_session(log_path, transcript_path, report_path)
    report = report_path.read_text(encoding='utf-8')

    assert 'EVENT TYPE BREAKDOWN' in report
    assert 'TOOL_RESULT' in report
    assert 'WIRE_RESPONSE' in report
    assert 'Tool outcomes: ok=1 fail=0' in report
    assert 'METADATA BREAKDOWN' in report
    assert 'By model:' in report
