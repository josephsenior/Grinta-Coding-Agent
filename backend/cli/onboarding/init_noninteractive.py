"""Non-interactive ``grinta init`` for CI, smoke scripts, and automation."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from backend.cli.onboarding.flow import (
    _default_model_for_api_key,
    _default_model_for_provider,
    _infer_provider_from_api_key,
    auto_detect_api_keys,
)
from backend.cli.onboarding.init_wizard import (
    _check_settings_directory_writable,
    _load_existing,
    _persist_api_key_safe,
    _provider_requires_api_key,
    _settings_path,
    _write_settings_file,
)
from backend.cli.onboarding.provider_presets import ONBOARDING_PROVIDER_PRESETS
from backend.cli.theme import CLR_BRAND, CLR_STATUS_WARN, no_color_enabled
from backend.core.config import load_app_config


def _resolve_api_key(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    direct = (os.environ.get('LLM_API_KEY') or '').strip()
    if direct:
        return direct
    config = load_app_config(set_logging_levels=False)
    auto_detect_api_keys(config)
    llm_cfg = config.get_llm_config()
    if llm_cfg.api_key is None:
        return ''
    return (
        llm_cfg.api_key.get_secret_value()
        if hasattr(llm_cfg.api_key, 'get_secret_value')
        else str(llm_cfg.api_key)
    ).strip()


def _resolve_provider(
    explicit: str | None,
    *,
    api_key: str,
    model: str,
) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip().lower()
    env_provider = (os.environ.get('LLM_PROVIDER') or '').strip().lower()
    if env_provider:
        return env_provider
    if '/' in model:
        return model.split('/', 1)[0].lower()
    inferred = _infer_provider_from_api_key(api_key)
    if inferred:
        return inferred
    return None


def _resolve_model(explicit: str | None, *, provider: str | None, api_key: str) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_model = (os.environ.get('LLM_MODEL') or '').strip()
    if env_model:
        return env_model
    if provider:
        preset = ONBOARDING_PROVIDER_PRESETS.get(provider, {})
        default_model = str(preset.get('default_model') or '').strip()
        if default_model:
            return default_model
        return _default_model_for_provider(provider)
    if api_key:
        return _default_model_for_api_key(api_key)
    return _default_model_for_provider(None)


def _resolve_base_url(explicit: str | None, *, provider: str) -> str:
    if explicit is not None:
        return explicit.strip()
    env_url = (os.environ.get('LLM_BASE_URL') or '').strip()
    if env_url:
        return env_url
    preset = ONBOARDING_PROVIDER_PRESETS.get(provider, {})
    return str(preset.get('base_url') or '').strip()


def _validate_provider(provider: str) -> str | None:
    if provider in ONBOARDING_PROVIDER_PRESETS:
        return None
    return (
        f"Unknown provider '{provider}'. "
        f'Choose one of: {", ".join(sorted(ONBOARDING_PROVIDER_PRESETS))}'
    )


def run_noninteractive_init(
    *,
    project_root: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    force: bool = False,
    console: Console | None = None,
) -> int:
    """Write ``settings.json`` from flags/env without the interactive wizard."""
    console = console or Console(no_color=no_color_enabled())
    if project_root is not None:
        project_root = project_root.resolve()

    settings_file = _settings_path()
    existing = _load_existing(settings_file)
    if existing and not force:
        console.print(
            f'[{CLR_STATUS_WARN}]Settings already exist at {settings_file}.[/]\n'
            'Pass --force to overwrite, or run interactive `grinta init`.',
            style=CLR_STATUS_WARN,
        )
        return 3

    writable, error = _check_settings_directory_writable(settings_file)
    if not writable:
        console.print(
            f'[{CLR_STATUS_WARN}]Cannot write settings: {error}[/]',
            style=CLR_STATUS_WARN,
        )
        return 2

    resolved_key = _resolve_api_key(api_key)
    resolved_model = _resolve_model(model, provider=None, api_key=resolved_key)
    resolved_provider = _resolve_provider(
        provider,
        api_key=resolved_key,
        model=resolved_model,
    )
    if not resolved_provider:
        console.print(
            f'[{CLR_STATUS_WARN}]Could not determine provider.[/]\n'
            'Set --provider or LLM_PROVIDER, or export a known API key '
            '(OPENAI_API_KEY, ANTHROPIC_API_KEY, ...).',
            style=CLR_STATUS_WARN,
        )
        return 3

    provider_err = _validate_provider(resolved_provider)
    if provider_err:
        console.print(f'[{CLR_STATUS_WARN}]{provider_err}[/]', style=CLR_STATUS_WARN)
        return 3

    if '/' not in resolved_model and resolved_provider:
        resolved_model = f'{resolved_provider}/{resolved_model}'

    resolved_base_url = _resolve_base_url(base_url, provider=resolved_provider)
    requires_key = _provider_requires_api_key(resolved_provider)
    if requires_key and not resolved_key:
        console.print(
            f'[{CLR_STATUS_WARN}]Provider {resolved_provider} requires an API key.[/]\n'
            'Set LLM_API_KEY or the provider env var before running '
            '`grinta init --non-interactive`.',
            style=CLR_STATUS_WARN,
        )
        return 3

    err = _write_settings_file(
        console,
        settings_file,
        resolved_provider,
        resolved_model,
        resolved_key,
        resolved_base_url,
    )
    if err is not None:
        return err

    _persist_api_key_safe(console, resolved_key, settings_file)

    console.print(
        f'Wrote [bold]{settings_file}[/bold]\n'
        f'Provider: [bold]{resolved_provider}[/bold]\n'
        f'Model: [bold]{resolved_model}[/bold]\n'
        f'Next: [{CLR_BRAND}]grinta doctor[/] then [{CLR_BRAND}]grinta[/]',
    )
    return 0


__all__ = ['run_noninteractive_init']
