"""Interactive onboarding flow."""

from __future__ import annotations

import logging
import os

from rich.console import Console

from backend.cli.onboarding.connection_check import _test_llm_call
from backend.cli.theme import (
    CLR_STATUS_ERR,
    no_color_enabled,
)
from backend.core.config import AppConfig, load_app_config

logger = logging.getLogger(__name__)
_console = Console(no_color=no_color_enabled())

from backend.cli.settings.constants import (
    DEFAULT_MODEL_BY_PROVIDER,
    DEFAULT_ONBOARDING_MODEL,
)


def needs_onboarding(config: AppConfig) -> bool:
    """Return True when no usable LLM API key is configured."""
    try:
        llm_cfg = config.get_llm_config()
        key = llm_cfg.api_key
        if key is None:
            return True
        raw = key.get_secret_value() if hasattr(key, 'get_secret_value') else str(key)
        return not raw or raw.strip() == ''
    except Exception:
        logger.debug('Could not read LLM config for onboarding check', exc_info=True)
        return True


def _iter_api_key_prefixes() -> list[tuple[str, str]]:
    from backend.core.providers import PROVIDER_CONFIGURATIONS

    prefixes: list[tuple[str, str]] = []
    for provider, cfg in PROVIDER_CONFIGURATIONS.items():
        for prefix in cfg.get('api_key_prefixes', []):
            if prefix:
                prefixes.append((prefix, provider))
    prefixes.sort(key=lambda item: len(item[0]), reverse=True)
    return prefixes


def _infer_provider_from_api_key(api_key: str | None) -> str | None:
    normalized = (api_key or '').strip()
    if not normalized:
        return None
    for prefix, provider in _iter_api_key_prefixes():
        if normalized.startswith(prefix):
            return provider
    return None


def _default_model_for_provider(provider: str | None) -> str:
    if not provider:
        return DEFAULT_ONBOARDING_MODEL
    return DEFAULT_MODEL_BY_PROVIDER.get(provider, DEFAULT_ONBOARDING_MODEL)


def _default_model_for_api_key(api_key: str | None) -> str:
    return _default_model_for_provider(_infer_provider_from_api_key(api_key))


def _default_model_from_environment() -> str | None:
    try:
        from backend.core.providers import PROVIDER_CONFIGURATIONS
    except Exception:
        logger.debug('Could not inspect provider configurations', exc_info=True)
        return None

    for provider, cfg in PROVIDER_CONFIGURATIONS.items():
        env_var = cfg.get('env_var')
        if not env_var:
            continue
        env_key = (os.environ.get(env_var) or '').strip()
        if env_key:
            return _default_model_for_provider(provider)
    return None


def auto_detect_api_keys(config: AppConfig) -> str | None:
    """Auto-detect API keys from environment variables.

    Checks standard env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
    and configures the LLM config if a key is found.

    Returns the detected provider name, or None if nothing found.
    """
    try:
        from pydantic import SecretStr

        from backend.core.providers import PROVIDER_CONFIGURATIONS
    except Exception:
        logger.debug('Could not import provider configurations', exc_info=True)
        return None

    llm_cfg = config.get_llm_config()

    for provider, cfg in PROVIDER_CONFIGURATIONS.items():
        env_var = cfg.get('env_var')
        if not env_var:
            continue
        env_key = (os.environ.get(env_var) or '').strip()
        if not env_key:
            continue

        llm_cfg.api_key = SecretStr(env_key)
        if not (getattr(llm_cfg, 'model', None) or '').strip():
            llm_cfg.model = _default_model_for_provider(provider)
        logger.info('Auto-detected API key from %s for provider %s', env_var, provider)
        return provider

    return None


def run_onboarding() -> AppConfig:
    """Interactive first-run setup via the shared ``grinta init`` wizard."""
    if not os.isatty(0):
        _console.print(
            f'[{CLR_STATUS_ERR}]No API key configured.[/]\n'
            'Run [bold]grinta init[/bold] in an interactive terminal to set provider, model, and API key,\n'
            'or create [bold]settings.json[/bold] and [bold].env[/bold] under your app settings root.'
        )
        raise SystemExit(1)

    from backend.cli.onboarding.init_wizard import run_init

    rc = run_init(console=_console)
    if rc != 0:
        raise SystemExit(rc)
    return load_app_config()


__all__ = [
    '_test_llm_call',
    'auto_detect_api_keys',
    'needs_onboarding',
    'run_onboarding',
]
