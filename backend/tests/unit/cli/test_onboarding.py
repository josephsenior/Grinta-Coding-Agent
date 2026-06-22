"""Tests for onboarding helpers."""

from __future__ import annotations

from backend.cli.settings.onboarding import needs_onboarding
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
