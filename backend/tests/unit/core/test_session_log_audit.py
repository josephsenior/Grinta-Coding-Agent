"""Tests for session log audit artifact generation."""

from __future__ import annotations

import json
from pathlib import Path

from backend.core.logging.session_log_audit import (
    analyze_session,
    generate_session_audit_artifacts,
)


def _write_json_line(path: Path, *, level: str, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(
            json.dumps(
                {
                    'timestamp': '2026-06-08 10:00:00,000',
                    'level': level,
                    'message': message,
                }
            )
            + '\n'
        )


def test_generate_session_audit_artifacts_writes_stripped_and_report(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv('GRINTA_SESSION_AUDIT', 'true')
    log_path = tmp_path / 'app.log'
    _write_json_line(
        log_path,
        level='INFO',
        message='on_event received StreamingChunkAction (id=1)',
    )
    _write_json_line(
        log_path,
        level='INFO',
        message='Setting agent(default) state from AgentState.RUNNING to AgentState.FINISHED',
    )
    _write_json_line(
        log_path,
        level='WARNING',
        message='Memory pressure WARNING (RSS=900 MB)',
    )

    result = generate_session_audit_artifacts(tmp_path)

    assert result is not None
    assert result.stripped_lines == 1
    assert result.kept_lines == 2
    assert (tmp_path / 'app.stripped.log').exists()
    assert (tmp_path / 'app.audit.txt').exists()
    report = (tmp_path / 'app.audit.txt').read_text(encoding='utf-8')
    assert 'VERDICT:' in report
    assert 'FINISHED' in report


def test_analyze_session_respects_disable_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('GRINTA_SESSION_AUDIT', 'false')
    log_path = tmp_path / 'app.log'
    _write_json_line(log_path, level='INFO', message='hello')

    assert generate_session_audit_artifacts(tmp_path) is None


def test_analyze_session_direct_paths(tmp_path: Path) -> None:
    log_path = tmp_path / 'app.log'
    stripped_path = tmp_path / 'app.stripped.log'
    report_path = tmp_path / 'app.audit.txt'
    _write_json_line(
        log_path,
        level='ERROR',
        message='pending action timed out after 120s',
    )

    result = analyze_session(log_path, stripped_path, report_path)

    assert result.verdict == 'ISSUES FOUND'
    assert stripped_path.read_text(encoding='utf-8').strip()
    assert 'pending action timed out' in report_path.read_text(encoding='utf-8')
