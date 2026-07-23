"""Tests for backend.cli.doctor.doctor_cli."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rich.console import Console

from backend.cli.doctor.doctor_cli import (
    DoctorCheck,
    _check_binary,
    _check_encoding,
    _check_llm_config,
    _check_package_manager_path,
    _check_settings_schema,
    cmd_doctor,
    collect_checks,
)

BREW_MAC = '/opt/homebrew/bin/brew'
BREW_LINUX = '/home/linuxbrew/.linuxbrew/bin/brew'
SCOOP_SHIMS = str(Path.home() / 'scoop' / 'shims')


def _quiet_console() -> Console:
    return Console(quiet=True)


def test_collect_checks_includes_core_rows() -> None:
    checks = collect_checks()
    names = {check.name for check in checks}
    assert {
        'version',
        'python',
        'platform',
        'settings',
        'llm',
        'git',
        'rg',
        'uv',
        'terminal_encoding',
    } <= names


def test_collect_checks_marks_uv_non_critical() -> None:
    checks = collect_checks()
    uv_check = next(check for check in checks if check.name == 'uv')
    assert uv_check.critical is False


def test_check_binary_found() -> None:
    with patch('backend.cli.doctor.checks.shutil.which', return_value='/usr/bin/git'):
        check = _check_binary('git')
    assert check.ok is True
    assert check.detail == '/usr/bin/git'


def test_check_binary_missing() -> None:
    with patch('backend.cli.doctor.checks.shutil.which', return_value=None):
        check = _check_binary('rg')
    assert check.ok is False
    assert 'PATH' in check.detail


def test_check_encoding_is_utf8() -> None:
    with patch(
        'backend.cli.doctor.checks.sys.stdout', SimpleNamespace(encoding='utf-8')
    ):
        check = _check_encoding()
    assert check.ok is True
    assert check.detail == 'utf-8'


def test_check_encoding_is_not_utf8() -> None:
    with patch(
        'backend.cli.doctor.checks.sys.stdout', SimpleNamespace(encoding='cp1252')
    ):
        check = _check_encoding()
    assert check.ok is False
    assert 'cp1252' in check.detail


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


@pytest.mark.parametrize(
    'os_name, exists_path, path_dirs, expected_ok, fragment',
    [
        (
            'macos',
            BREW_MAC,
            ['/opt/homebrew/bin'],
            True,
            'on PATH',
        ),  # on mac + brew installed + on path
        (
            'macos',
            BREW_MAC,
            ['/usr/bin'],
            False,
            'not on PATH',
        ),  # on mac + brew installed + not on path
        (
            'linux',
            BREW_LINUX,
            ['/home/linuxbrew/.linuxbrew/bin'],
            True,
            'on PATH',
        ),  # on linux + brew installed + on path
        (
            'windows',
            SCOOP_SHIMS,
            [SCOOP_SHIMS],
            True,
            'on PATH',
        ),  # on windows + scoop installed + on path
        (
            'windows',
            SCOOP_SHIMS,
            ['C:/other'],
            False,
            'not on PATH',
        ),  # on windows + scoop installed + not on path
        ('macos', None, ['/usr/bin'], True, 'not detected'),  # on mac + not detected
        ('other', None, [], True, 'n/a'),  # other os
    ],
)
def test_package_manager_path(
    monkeypatch, os_name, exists_path, path_dirs, expected_ok, fragment
) -> None:
    for name in ('is_windows', 'is_macos', 'is_linux'):
        monkeypatch.setattr(
            f'backend.cli.doctor.checks.{name}', lambda n=name: n == f'is_{os_name}'
        )
        monkeypatch.setattr(
            'backend.cli.doctor.checks.Path.exists',
            lambda self: (
                str(self) == exists_path
            ),  # None -> never matched -> not installed
        )
    monkeypatch.setenv('PATH', os.pathsep.join(path_dirs))

    check = _check_package_manager_path()
    assert check.ok is expected_ok
    assert fragment in check.detail
