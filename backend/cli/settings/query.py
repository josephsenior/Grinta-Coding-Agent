"""Settings queries and programmatic updates."""

from __future__ import annotations

import logging
import os
from typing import Any

from rich.console import Console

from backend.cli.theme import (
    no_color_enabled,
)
from backend.core.config import AppConfig
from backend.core.config.dotenv_keys import (
    persist_llm_api_key_to_dotenv,
    persist_provider_api_key_to_dotenv,
)
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER

logger = logging.getLogger(__name__)
_console = Console(no_color=no_color_enabled())

from backend.cli.settings.onboarding import (
    _default_model_for_api_key,
    _default_model_from_environment,
)
from backend.cli.settings.storage import (
    _load_raw_settings,
    _save_raw_settings,
    _settings_path,
)


def ensure_default_model(config: AppConfig) -> str | None:
    """Ensure the active LLM config has a usable model when a key exists."""
    llm_cfg = config.get_llm_config()
    model = (getattr(llm_cfg, 'model', None) or '').strip()
    if model:
        return model

    raw_key = _resolve_api_key_value(config)
    if raw_key:
        inferred_model = _default_model_for_api_key(raw_key)
        llm_cfg.model = inferred_model
        return inferred_model

    env_model = _default_model_from_environment()
    if not env_model:
        return None
    llm_cfg.model = env_model
    return env_model


def get_current_model(config: AppConfig) -> str:
    try:
        return config.get_llm_config().model or '(not set)'
    except Exception:
        logger.debug('Could not read current model from config', exc_info=True)
        return '(not set)'


def get_current_provider(config: AppConfig) -> str | None:
    try:
        from backend.inference.provider_resolver import extract_provider_prefix

        llm_cfg = config.get_llm_config()
        raw_provider = getattr(llm_cfg, 'custom_llm_provider', None)
        configured = _sanitize_llm_provider(raw_provider) or ''
        if configured:
            return configured
        model = (getattr(llm_cfg, 'model', None) or '').strip()
        if not model:
            return None
        prefixed = extract_provider_prefix(model)
        if prefixed:
            return prefixed
        from backend.inference.catalog_loader import lookup

        entry = lookup(model)
        return entry.provider if entry else None
    except Exception:
        logger.debug('Could not read current provider from config', exc_info=True)
        return None


def _resolve_api_key_value(
    config: AppConfig, provider: str | None = None
) -> str | None:
    if provider:
        try:
            from backend.core.config.api_key_manager import api_key_manager

            provider_key = api_key_manager.get_provider_key_from_env(provider)
            if provider_key and provider_key.strip():
                return provider_key.strip()
        except Exception:
            logger.debug('Could not resolve provider API key', exc_info=True)

    llm_cfg = config.get_llm_config()
    raw = _api_key_from_llm_cfg(llm_cfg)
    if raw:
        return raw

    model = (getattr(llm_cfg, 'model', '') or '').strip()
    env_raw = _api_key_from_env_for_model(model) if model else None
    if env_raw:
        return env_raw

    fallback = (os.environ.get('LLM_API_KEY') or '').strip()
    return fallback or None


def _api_key_from_llm_cfg(llm_cfg: Any) -> str | None:
    api_key: Any = getattr(llm_cfg, 'api_key', None)
    if api_key is None:
        return None
    try:
        raw = api_key.get_secret_value()
    except AttributeError:
        raw = str(api_key)
    raw = raw.strip()
    return raw or None


def _api_key_from_env_for_model(model: str) -> str | None:
    try:
        from backend.core.config.api_key_manager import api_key_manager

        provider = api_key_manager.extract_provider(model)
        env_key = api_key_manager.get_provider_key_from_env(provider)
        if env_key and env_key.strip():
            return env_key.strip()
    except Exception:
        logger.debug('Could not resolve env-backed API key', exc_info=True)
    return None


def _mask_secret(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return '(not set)'
    if len(raw) <= 4:
        return '•' * len(raw)
    if len(raw) <= 8:
        visible = 2
        return raw[:visible] + '•' * (len(raw) - (visible * 2)) + raw[-visible:]
    return raw[:4] + '•' * min(len(raw) - 8, 20) + raw[-4:]


def get_masked_api_key(config: AppConfig, provider: str | None = None) -> str:
    try:
        raw = _resolve_api_key_value(config, provider)
        if not raw:
            return '(not set)'
        return _mask_secret(raw)
    except Exception:
        logger.debug('Could not read API key for masking', exc_info=True)
        return '(not set)'


def _sanitize_llm_provider(value: Any) -> str | None:
    """Return a safe provider slug for settings.json, or None if invalid."""
    if value is None:
        return None
    if not isinstance(value, str):
        module = getattr(type(value), '__module__', '')
        if module.startswith('unittest.mock'):
            return None
        value = str(value)
    text = value.strip().lower()
    if not text or 'magicmock' in text or text.startswith('<'):
        return None
    return text


def get_persisted_reasoning_effort() -> str:
    """Return the user-configured reasoning effort from settings.json (empty = default)."""
    raw = _load_raw_settings().get('llm_reasoning_effort')
    if raw is None:
        return ''
    return str(raw).strip()


def update_reasoning_effort(effort: str | None) -> None:
    """Persist reasoning effort without touching model or provider fields."""
    settings = _load_raw_settings()
    if effort and str(effort).strip():
        settings['llm_reasoning_effort'] = str(effort).strip()
    else:
        settings.pop('llm_reasoning_effort', None)
    _save_raw_settings(settings)


def update_model(
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
    reasoning_effort: str | None = None,
    clear_base_url: bool = False,
) -> None:
    settings = _load_raw_settings()
    settings['llm_model'] = model
    provider = _sanitize_llm_provider(provider)
    if provider:
        settings['llm_provider'] = provider
    if base_url:
        settings['llm_base_url'] = base_url
    elif clear_base_url:
        settings.pop('llm_base_url', None)
    if reasoning_effort and str(reasoning_effort).strip():
        settings['llm_reasoning_effort'] = str(reasoning_effort).strip()
    else:
        settings.pop('llm_reasoning_effort', None)
    _save_raw_settings(settings)


def update_api_key(key: str, provider: str | None = None) -> None:
    settings = _load_raw_settings()
    settings['llm_api_key'] = LLM_API_KEY_SETTINGS_PLACEHOLDER
    _save_raw_settings(settings)
    if provider and provider.strip():
        persist_provider_api_key_to_dotenv(
            provider.strip().lower(), key, settings_json_path=_settings_path()
        )
    persist_llm_api_key_to_dotenv(key, settings_json_path=_settings_path())


def update_budget(budget: float | None) -> None:
    settings = _load_raw_settings()
    if budget is None or budget <= 0:
        settings.pop('max_budget_per_task', None)
    else:
        settings['max_budget_per_task'] = budget
    _save_raw_settings(settings)


def update_cli_tool_icons(enabled: bool) -> None:
    settings = _load_raw_settings()
    settings['cli_tool_icons'] = bool(enabled)
    _save_raw_settings(settings)


def get_cli_tool_icons_enabled(config: AppConfig) -> bool:
    return bool(getattr(config, 'cli_tool_icons', True))


def get_budget(config: AppConfig) -> str:
    budget = getattr(config, 'max_budget_per_task', None)
    if budget is None:
        return 'unlimited'
    return f'${budget:.2f}'
