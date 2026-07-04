"""Interactive onboarding flow (needs check, env key detect, run wizard)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console

from backend.cli.onboarding.connection_check import _test_llm_call
from backend.cli.onboarding.settings_defaults import (
    build_init_settings,
    settings_api_key_value,
)
from backend.cli.theme import (
    CLR_STATUS_ERR,
    no_color_enabled,
)
from backend.core.app_paths import get_canonical_settings_path
from backend.core.config import AppConfig, load_app_config
from backend.inference.local_model import is_local_llm_config

logger = logging.getLogger(__name__)
_console = Console(no_color=no_color_enabled())


def needs_onboarding(config: AppConfig) -> bool:
    """Return True when no usable LLM configuration is available."""
    try:
        llm_cfg = config.get_llm_config()
        key = llm_cfg.api_key
        if key is not None:
            raw = (
                key.get_secret_value() if hasattr(key, 'get_secret_value') else str(key)
            )
            if raw and raw.strip():
                return False
        if is_local_llm_config(llm_cfg):
            return False
        return True
    except Exception:
        logger.debug('Could not read LLM config for onboarding check', exc_info=True)
        return True


def _iter_api_key_prefixes() -> list[tuple[str, str]]:
    from backend.core.providers.configurations import PROVIDER_CONFIGURATIONS

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
    from backend.cli.settings.constants import (
        DEFAULT_MODEL_BY_PROVIDER,
        DEFAULT_ONBOARDING_MODEL,
    )

    if not provider:
        return DEFAULT_ONBOARDING_MODEL
    return DEFAULT_MODEL_BY_PROVIDER.get(provider, DEFAULT_ONBOARDING_MODEL)


def _default_model_for_api_key(api_key: str | None) -> str:
    return _default_model_for_provider(_infer_provider_from_api_key(api_key))


def _default_model_from_environment() -> str | None:
    try:
        from backend.core.providers.configurations import PROVIDER_CONFIGURATIONS
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

        from backend.core.providers.configurations import PROVIDER_CONFIGURATIONS
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


def _settings_file_needs_env_persist(settings_path: Path) -> bool:
    """Return True when env-detected credentials should be written to disk.

    A malformed existing file is treated as a hard stop: we refuse to overwrite
    it, because the user may have intentional customisations in other sections
    (security, mcp_config, agent, …) that env-detection would silently clobber.
    """
    if not settings_path.is_file():
        return True
    try:
        data = json.loads(settings_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            'Refusing to overwrite malformed settings.json at %s (%s). '
            'Fix the file manually or run `grinta init` to rebuild it.',
            settings_path,
            exc,
        )
        return False
    if not isinstance(data, dict):
        logger.warning(
            'Refusing to overwrite settings.json at %s: top-level value is %s, '
            'not an object.',
            settings_path,
            type(data).__name__,
        )
        return False
    provider = str(data.get('llm_provider') or '').strip()
    model = str(data.get('llm_model') or '').strip()
    return not provider and not model


def _read_existing_settings(settings_path: Path) -> dict[str, Any] | None:
    """Return parsed settings.json or None when missing / unparseable."""
    if not settings_path.is_file():
        return None
    try:
        data = json.loads(settings_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_persisted_api_key(
    config: AppConfig,
    explicit: str | None,
) -> str:
    secret = explicit
    if secret is None:
        llm_cfg = config.get_llm_config()
        if llm_cfg.api_key is not None:
            secret = (
                llm_cfg.api_key.get_secret_value()
                if hasattr(llm_cfg.api_key, 'get_secret_value')
                else str(llm_cfg.api_key)
            )
    return (secret or '').strip()


def persist_env_detected_settings(
    config: AppConfig,
    provider: str,
    *,
    api_key: str | None = None,
) -> bool:
    """Persist minimal ``settings.json`` after env key auto-detection.

    Behaviour:
    * Missing file → write the full init-shaped settings so first-run users
      have a complete ``security`` / ``mcp_config`` / ``agent`` baseline.
    * Existing valid file → merge only the LLM-related top-level fields
      (``llm_provider`` / ``llm_model`` / ``llm_api_key`` placeholder /
      ``llm_base_url``). Other sections are preserved so user
      customisations are never clobbered.
    * Existing malformed file → refuse to write (see
      :func:`_settings_file_needs_env_persist`).
    """
    from backend.cli.onboarding.init_wizard import (
        _atomic_json_write,
        _check_settings_directory_writable,
    )

    settings_path = Path(get_canonical_settings_path())
    if not _settings_file_needs_env_persist(settings_path):
        return False

    writable, error = _check_settings_directory_writable(settings_path)
    if not writable:
        logger.warning('Could not persist env-detected settings: %s', error)
        return False

    llm_cfg = config.get_llm_config()
    model = (getattr(llm_cfg, 'model', None) or '').strip()
    if not model:
        model = _default_model_for_provider(provider)
    base_url = (getattr(llm_cfg, 'base_url', None) or '').strip()
    secret = _resolve_persisted_api_key(config, api_key)

    existing = _read_existing_settings(settings_path)
    if existing is None:
        # First run — emit a complete init-shaped file.
        settings = build_init_settings(
            provider=provider,
            model=model,
            api_key=secret,
            base_url=base_url,
            requires_api_key=True,
        )
    else:
        # Subsequent run — merge only the LLM-related keys.
        merged_settings: dict[str, Any] = dict(existing)
        merged_settings['llm_provider'] = provider
        merged_settings['llm_model'] = model
        merged_settings['llm_api_key'] = settings_api_key_value(
            provider, secret, requires_key=True
        )
        if base_url:
            merged_settings['llm_base_url'] = base_url
        # Never blank out a user-configured base_url when env has none.
        settings = merged_settings

    try:
        _atomic_json_write(settings_path, settings)
    except OSError:
        logger.warning('Failed to write env-detected settings', exc_info=True)
        return False

    if secret:
        try:
            from backend.core.config.dotenv_keys import persist_llm_api_key_to_dotenv

            persist_llm_api_key_to_dotenv(secret, settings_json_path=settings_path)
        except OSError:
            logger.warning(
                'Failed to persist env-detected API key to .env', exc_info=True
            )
    return True


def run_onboarding() -> AppConfig:
    """Interactive first-run setup via the shared ``grinta init`` wizard."""
    if not os.isatty(0):
        _console.print(
            f'[{CLR_STATUS_ERR}]No API key configured.[/]\n'
            'Run [bold]grinta init[/bold] in an interactive terminal, '
            '[bold]grinta init --non-interactive[/bold] with LLM_API_KEY set, '
            'or create [bold]settings.json[/bold] and [bold].env[/bold] under your app settings root.'
        )
        raise SystemExit(1)

    from backend.cli.onboarding.init_wizard import run_init

    rc = run_init(console=_console)
    if rc != 0:
        raise SystemExit(rc)
    return load_app_config()


__all__ = [
    '_default_model_for_api_key',
    '_default_model_from_environment',
    '_test_llm_call',
    'auto_detect_api_keys',
    'needs_onboarding',
    'persist_env_detected_settings',
    'run_onboarding',
]
