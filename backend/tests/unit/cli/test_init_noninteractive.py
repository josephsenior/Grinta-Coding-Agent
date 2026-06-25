"""Tests for non-interactive ``grinta init``."""

from __future__ import annotations

import json

import pytest
from rich.console import Console

from backend.cli.onboarding.init_noninteractive import run_noninteractive_init


@pytest.fixture
def isolated_app_root(tmp_path, monkeypatch):
    app_root = tmp_path / 'app'
    app_root.mkdir()
    monkeypatch.setenv('APP_ROOT', str(app_root))
    return app_root


def test_noninteractive_init_writes_settings_from_env(
    isolated_app_root, monkeypatch
) -> None:
    monkeypatch.setenv('LLM_API_KEY', 'sk-test-key')
    monkeypatch.setenv('LLM_PROVIDER', 'openai')

    rc = run_noninteractive_init(
        force=True,
        console=Console(quiet=True),
    )

    assert rc == 0
    settings_path = isolated_app_root / 'settings.json'
    assert settings_path.is_file()
    data = json.loads(settings_path.read_text(encoding='utf-8'))
    assert data['llm_provider'] == 'openai'
    assert data['agent']['Orchestrator']['mode'] == 'agent'
    assert data['security']['execution_profile'] == 'standard'


def test_noninteractive_init_refuses_overwrite_without_force(
    isolated_app_root, monkeypatch
) -> None:
    settings_path = isolated_app_root / 'settings.json'
    settings_path.write_text('{"llm_provider": "openai"}', encoding='utf-8')
    monkeypatch.setenv('LLM_API_KEY', 'sk-test-key')
    monkeypatch.setenv('LLM_PROVIDER', 'openai')

    rc = run_noninteractive_init(console=Console(quiet=True))

    assert rc == 3
    assert json.loads(settings_path.read_text(encoding='utf-8')) == {
        'llm_provider': 'openai'
    }


def test_noninteractive_init_local_provider_without_api_key(
    isolated_app_root, monkeypatch
) -> None:
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    monkeypatch.setenv('LLM_MODEL', 'ollama/llama3.2')

    rc = run_noninteractive_init(
        force=True,
        console=Console(quiet=True),
    )

    assert rc == 0
    data = json.loads((isolated_app_root / 'settings.json').read_text(encoding='utf-8'))
    assert data['llm_provider'] == 'ollama'
    assert data['llm_model'] == 'ollama/llama3.2'
