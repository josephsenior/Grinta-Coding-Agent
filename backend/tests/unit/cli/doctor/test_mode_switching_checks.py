"""Doctor checks for mode-switching configuration hygiene."""

from __future__ import annotations

import json

from backend.cli.doctor.checks import (
    check_legacy_autonomy_alias,
    check_security_settings_values,
)


def test_check_legacy_autonomy_alias_flags_supervised(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({'agent': {'agent': {'autonomy_level': 'supervised'}}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    check = check_legacy_autonomy_alias()

    assert check.ok is False
    assert 'supervised' in check.detail


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
