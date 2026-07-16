"""Tests for shared /health check registry."""

from __future__ import annotations

import json

from backend.cli.doctor.checks import (
    check_security_settings_values,
    collect_health_checks,
    format_health_report_lines,
)


def test_collect_health_checks_returns_fast_subset() -> None:
    checks = collect_health_checks()
    names = {check.name for check in checks}
    assert {'git', 'rg', 'llm', 'security_values', 'execution'}.issubset(names)


def test_collect_health_checks_uses_model_hint() -> None:
    checks = collect_health_checks(model_hint='openai/gpt-4.1')
    model_checks = [check for check in checks if check.name == 'model']
    assert len(model_checks) == 1
    assert model_checks[0].detail == 'openai/gpt-4.1'


def test_format_health_report_lines_marks_failures() -> None:
    from backend.cli.doctor.checks import DoctorCheck

    lines = format_health_report_lines([DoctorCheck('git', False, 'not found on PATH')])
    assert lines[0] == 'Self-check:'
    assert '[FAIL]' in lines[1]


def test_check_security_settings_values_rejects_unknown_profile(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({'security': {'execution_profile': 'ultra_hardened'}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    check = check_security_settings_values()

    assert check.ok is False
    assert 'ultra_hardened' in check.detail


def test_check_security_settings_values_accepts_sandboxed_local(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({'security': {'execution_profile': 'sandboxed_local'}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    check = check_security_settings_values()

    assert check.ok is True
    assert 'sandboxed_local' in check.detail
