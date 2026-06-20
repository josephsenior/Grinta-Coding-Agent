"""Shared provider presets for ``grinta init`` and launch-time onboarding."""

from __future__ import annotations

from backend.cli.settings.constants import (
    _PROVIDERS,
    DEFAULT_MODEL_BY_PROVIDER,
)
from backend.core.providers.configurations import PROVIDER_CONFIGURATIONS
from backend.inference.catalog.provider_catalog import PROVIDER_DEFAULT_URLS

_LOCAL_BASE_URLS: dict[str, str] = {
    'ollama': 'http://localhost:11434',
    'lm_studio': 'http://localhost:1234/v1',
    'vllm': 'http://localhost:8000/v1',
}

_LOCAL_DEFAULT_MODELS: dict[str, str] = {
    'ollama': 'ollama/llama3.2',
    'lm_studio': 'lm_studio/local-model',
    'vllm': 'vllm/local-model',
}


def _help_text(key: str, label: str, category: str) -> str:
    if category == 'local':
        return f'Local {label}'
    if key == 'openai':
        return 'OpenAI / compatible (gpt-4o, gpt-5.x, ...)'
    if key == 'anthropic':
        return 'Anthropic (claude-sonnet-4-6, claude-opus-4-7, claude-haiku-4-5, ...)'
    if key == 'google':
        return 'Google Gemini (gemini-2.5-pro, gemini-3-flash, ...)'
    if key == 'openrouter':
        return 'OpenRouter (proxy to many providers)'
    if key == 'vercel':
        return 'Vercel AI Gateway (OpenAI-compatible, 200+ models)'
    if key == 'moonshot':
        return 'Moonshot Kimi API (kimi-k2.5, kimi-k2.6, kimi-k2.7-code, ...)'
    return label


def build_provider_presets() -> dict[str, dict[str, str]]:
    """Return onboarding presets keyed by provider id."""
    presets: dict[str, dict[str, str]] = {}
    for key, label, category in _PROVIDERS:
        cfg = PROVIDER_CONFIGURATIONS.get(key, {})
        env_var = str(cfg.get('env_var') or '')
        if category == 'local':
            base_url = _LOCAL_BASE_URLS[key]
            default_model = _LOCAL_DEFAULT_MODELS[key]
        else:
            base_url = PROVIDER_DEFAULT_URLS.get(key, '')
            default_model = DEFAULT_MODEL_BY_PROVIDER.get(
                key, f'{key}/local-model' if category == 'local' else ''
            )
        presets[key] = {
            'env': env_var,
            'default_model': default_model,
            'base_url': base_url,
            'help': _help_text(key, label, category),
        }
    return presets


ONBOARDING_PROVIDER_PRESETS: dict[str, dict[str, str]] = build_provider_presets()
