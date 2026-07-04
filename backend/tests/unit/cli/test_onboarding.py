"""Tests for onboarding helpers."""

from __future__ import annotations

import json

from backend.cli.onboarding import needs_onboarding
from backend.core.config import AppConfig


def _config_with_model(model: str, *, base_url: str = '') -> AppConfig:
    config = AppConfig()
    llm_cfg = config.get_llm_config()
    llm_cfg.model = model
    llm_cfg.api_key = None
    if base_url:
        llm_cfg.base_url = base_url
    return config


def test_needs_onboarding_false_for_ollama_without_api_key() -> None:
    config = _config_with_model('ollama/llama3.2')
    assert needs_onboarding(config) is False


def test_needs_onboarding_false_for_lm_studio_without_api_key() -> None:
    config = _config_with_model('lm_studio/local-model')
    assert needs_onboarding(config) is False


def test_needs_onboarding_false_for_vllm_without_api_key() -> None:
    config = _config_with_model('vllm/mistral')
    assert needs_onboarding(config) is False


def test_needs_onboarding_false_for_localhost_base_url_without_api_key() -> None:
    config = _config_with_model('custom/model', base_url='http://localhost:11434')
    assert needs_onboarding(config) is False


def test_needs_onboarding_true_for_cloud_model_without_api_key() -> None:
    config = _config_with_model('openai/gpt-4.1')
    assert needs_onboarding(config) is True


def test_needs_onboarding_false_when_api_key_present() -> None:
    from pydantic import SecretStr

    config = _config_with_model('openai/gpt-4.1')
    config.get_llm_config().api_key = SecretStr('sk-test-key')
    assert needs_onboarding(config) is False


def test_ollama_init_settings_do_not_require_onboarding() -> None:
    """Regression: keyless Ollama init output must allow launching the TUI."""
    config = AppConfig()
    llm_cfg = config.get_llm_config()
    llm_cfg.model = 'ollama/llama3.2'
    llm_cfg.api_key = None
    llm_cfg.custom_llm_provider = 'ollama'
    llm_cfg.base_url = 'http://localhost:11434'
    assert needs_onboarding(config) is False


def test_persist_env_detected_settings_writes_minimal_file(
    tmp_path,
    monkeypatch,
) -> None:
    from pydantic import SecretStr

    from backend.cli.onboarding.flow import persist_env_detected_settings
    from backend.cli.onboarding.settings_defaults import default_init_security_block

    settings_file = tmp_path / 'settings.json'
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    config = AppConfig()
    llm_cfg = config.get_llm_config()
    llm_cfg.api_key = SecretStr('sk-test-openai-key')
    llm_cfg.model = 'openai/gpt-4.1'

    assert (
        persist_env_detected_settings(
            config,
            'openai',
            api_key='sk-test-openai-key',
        )
        is True
    )

    data = json.loads(settings_file.read_text(encoding='utf-8'))
    assert data['llm_provider'] == 'openai'
    assert data['llm_model'] == 'openai/gpt-4.1'
    assert data['security'] == default_init_security_block()
    assert 'mcp_config' in data


def test_persist_env_detected_settings_skips_existing_provider(
    tmp_path,
    monkeypatch,
) -> None:
    from backend.cli.onboarding.flow import persist_env_detected_settings

    settings_file = tmp_path / 'settings.json'
    settings_file.write_text(
        json.dumps({'llm_provider': 'anthropic', 'llm_model': 'anthropic/claude'}),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    config = AppConfig()
    assert persist_env_detected_settings(config, 'openai', api_key='sk-test') is False


def test_persist_env_detected_settings_preserves_user_customisations(
    tmp_path,
    monkeypatch,
) -> None:
    """Regression: env-detection must not clobber the user's security / mcp sections."""
    from pydantic import SecretStr

    from backend.cli.onboarding.flow import persist_env_detected_settings

    settings_file = tmp_path / 'settings.json'
    user_security = {
        'execution_profile': 'hardened_local',
        'allow_network_commands': True,
    }
    user_mcp = {'my_server': {'command': 'uvx', 'args': ['my-mcp']}}
    settings_file.write_text(
        json.dumps(
            {
                'security': user_security,
                'mcp_config': user_mcp,
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    config = AppConfig()
    llm_cfg = config.get_llm_config()
    llm_cfg.api_key = SecretStr('sk-test-openai-key')
    llm_cfg.model = 'openai/gpt-4.1'

    assert (
        persist_env_detected_settings(config, 'openai', api_key='sk-test-openai-key')
        is True
    )

    data = json.loads(settings_file.read_text(encoding='utf-8'))
    assert data['llm_provider'] == 'openai'
    assert data['llm_model'] == 'openai/gpt-4.1'
    # The whole point: user customisations are preserved.
    assert data['security'] == user_security
    assert data['mcp_config'] == user_mcp


def test_persist_env_detected_settings_refuses_to_overwrite_malformed_file(
    tmp_path,
    monkeypatch,
) -> None:
    """Regression: a malformed settings.json must not be silently replaced."""
    from backend.cli.onboarding.flow import persist_env_detected_settings

    settings_file = tmp_path / 'settings.json'
    original_content = '{not valid json,'
    settings_file.write_text(original_content, encoding='utf-8')
    monkeypatch.setenv('APP_ROOT', str(tmp_path))

    config = AppConfig()
    assert persist_env_detected_settings(config, 'openai', api_key='sk-test') is False
    # File is byte-for-byte unchanged.
    assert settings_file.read_text(encoding='utf-8') == original_content
