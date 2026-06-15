"""Additional unit tests for init wizard helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.cli.onboarding.init_wizard import (
    _atomic_json_write,
    _is_env_placeholder,
    _is_global_settings,
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
