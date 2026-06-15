"""Additional unit tests for init wizard helpers."""

from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from backend.cli.onboarding.init_wizard import (
    _atomic_json_write,
    _check_settings_directory_writable,
    _is_env_placeholder,
    _is_global_settings,
    _load_existing,
    _provider_requires_api_key,
    _settings_api_key_value,
)
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER


def test_provider_requires_api_key() -> None:
    assert _provider_requires_api_key('openai') is True
    assert _provider_requires_api_key('ollama') is False
    assert _provider_requires_api_key('lm_studio') is False


def test_settings_api_key_value_uses_placeholder_for_env_providers() -> None:
    assert _settings_api_key_value('openai', 'sk-test') == LLM_API_KEY_SETTINGS_PLACEHOLDER
    assert _settings_api_key_value('ollama', '') == ''


def test_is_env_placeholder() -> None:
    assert _is_env_placeholder('${OPENAI_API_KEY}') is True
    assert _is_env_placeholder('sk-real-key') is False


def test_atomic_json_write_creates_valid_file(tmp_path: Path) -> None:
    target = tmp_path / 'settings.json'
    data = {'llm_provider': 'openai', 'llm_model': 'gpt-4o'}
    _atomic_json_write(target, data)
    assert target.exists()
    assert json.loads(target.read_text(encoding='utf-8')) == data


def test_is_global_settings_detects_home_grinta_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    global_settings = tmp_path / '.grinta' / 'settings.json'
    global_settings.parent.mkdir(parents=True)
    global_settings.write_text('{}', encoding='utf-8')
    assert _is_global_settings(global_settings) is True
    assert _is_global_settings(tmp_path / 'project' / 'settings.json') is False


def test_check_settings_directory_writable_existing_dir(tmp_path: Path) -> None:
    settings_path = tmp_path / 'settings.json'
    ok, message = _check_settings_directory_writable(settings_path)
    assert ok is True
    assert message == ''


def test_load_existing_handles_missing_and_invalid_json(tmp_path: Path) -> None:
    missing = tmp_path / 'missing.json'
    assert _load_existing(missing) == {}
    bad = tmp_path / 'bad.json'
    bad.write_text('{not json', encoding='utf-8')
    assert _load_existing(bad) == {}


def test_get_platform_info_includes_os_name() -> None:
    from backend.cli.onboarding.init_wizard import _get_platform_info

    assert platform.system() in _get_platform_info()


def test_settings_path_uses_canonical_location(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.cli.onboarding.init_wizard import _settings_path

    monkeypatch.setattr(
        'backend.cli.onboarding.init_wizard.get_canonical_settings_path',
        lambda: str(Path('/tmp/grinta/settings.json')),
    )
    assert _settings_path() == Path('/tmp/grinta/settings.json')
