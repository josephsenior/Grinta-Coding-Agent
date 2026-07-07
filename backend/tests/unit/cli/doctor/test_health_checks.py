"""Tests for shared /health check registry."""

from __future__ import annotations

from backend.cli.doctor.checks import (
    collect_health_checks,
    format_health_report_lines,
)


def test_collect_health_checks_returns_fast_subset() -> None:
    checks = collect_health_checks()
    names = {check.name for check in checks}
    assert {'debugpy', 'git', 'rg', 'llm', 'security_values', 'execution'}.issubset(
        names
    )


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
