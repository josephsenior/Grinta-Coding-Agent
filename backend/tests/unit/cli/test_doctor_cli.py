"""Tests for backend.cli.doctor.doctor_cli."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from backend.cli.doctor.doctor_cli import (
    DoctorCheck,
    _check_binary,
    _check_llm_config,
    _check_settings_schema,
    cmd_doctor,
    collect_checks,
)


def _quiet_console() -> Console:
    return Console(quiet=True)


def test_collect_checks_includes_core_rows() -> None:
    checks = collect_checks()
    names = {check.name for check in checks}
    assert {'version', 'python', 'platform', 'settings', 'llm', 'git', 'rg'} <= names


def test_check_binary_found() -> None:
    with patch(
        'backend.cli.doctor.doctor_cli.shutil.which', return_value='/usr/bin/git'
    ):
        check = _check_binary('git')
    assert check.ok is True
    assert check.detail == '/usr/bin/git'


def test_check_binary_missing() -> None:
    with patch('backend.cli.doctor.doctor_cli.shutil.which', return_value=None):
        check = _check_binary('rg')
    assert check.ok is False
    assert 'PATH' in check.detail


def test_check_settings_schema_flags_nested_agent(tmp_path: Path, monkeypatch) -> None:
    settings = {
        'llm_model': 'openai/gpt-4.1',
        'llm_api_key': '${LLM_API_KEY}',
        'agent': {'agent': {'autonomy_level': 'balanced'}},
    }
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(json.dumps(settings), encoding='utf-8')
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    check = _check_settings_schema()
    assert check.ok is False
    assert 'agent.agent' in check.detail


def test_cmd_doctor_returns_1_on_critical_failure() -> None:
    checks = [
        DoctorCheck('settings', False, 'missing', critical=True),
        DoctorCheck('debugpy', False, 'optional', critical=False),
    ]
    with patch('backend.cli.doctor.doctor_cli.collect_checks', return_value=checks):
        rc = cmd_doctor(_quiet_console())
    assert rc == 1


def test_cmd_doctor_returns_0_when_only_optional_warnings() -> None:
    checks = [
        DoctorCheck('settings', True, 'ok'),
        DoctorCheck('debugpy', False, 'optional', critical=False),
    ]
    with patch('backend.cli.doctor.doctor_cli.collect_checks', return_value=checks):
        rc = cmd_doctor(_quiet_console())
    assert rc == 0


def test_check_llm_config_passes_for_local_provider_without_key(
    tmp_path: Path, monkeypatch
) -> None:
    settings = {
        'llm_provider': 'ollama',
        'llm_model': 'ollama/llama3.2',
        'llm_api_key': '',
    }
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(json.dumps(settings), encoding='utf-8')
    monkeypatch.setenv('APP_ROOT', str(tmp_path))
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('OPENCODE_API_KEY', raising=False)

    check = _check_llm_config()
    assert check.ok is True
    assert 'key=not required' in check.detail


def test_verbose_collect_includes_editing_stack() -> None:
    checks = collect_checks(verbose=True)
    assert any(check.name == 'editing_stack' for check in checks)
