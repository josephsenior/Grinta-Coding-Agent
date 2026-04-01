"""Configuration management — onboarding, settings I/O, API key handling."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from backend.core.config import AppConfig, load_app_config

_console = Console()
_DEFAULT_ONBOARDING_MODEL = 'openai/gpt-4.1'
_DEFAULT_MODEL_BY_PROVIDER = {
    'anthropic': 'anthropic/claude-sonnet-4-20250514',
    'google': 'google/gemini-2.5-flash',
    'groq': 'groq/meta-llama/llama-4-scout',
    'lightning': 'lightning/meta-llama/Meta-Llama-3.1-8B-Instruct',
    'openai': _DEFAULT_ONBOARDING_MODEL,
    'openrouter': 'openrouter/anthropic/claude-3.5-sonnet',
    'xai': 'xai/grok-4.1-fast',
}

# Providers shown during onboarding, in display order
_ONBOARDING_PROVIDERS: list[tuple[str, str]] = [
    ('openai', 'OpenAI'),
    ('anthropic', 'Anthropic'),
    ('google', 'Google (Gemini)'),
    ('groq', 'Groq'),
    ('xai', 'xAI (Grok)'),
    ('openrouter', 'OpenRouter'),
    ('lightning', 'Lightning AI'),
    ('deepseek', 'DeepSeek'),
    ('nvidia', 'NVIDIA'),
    ('ollama', 'Ollama (local)'),
    ('lm_studio', 'LM Studio (local)'),
]

# ---------------------------------------------------------------------------
# Settings file location
# ---------------------------------------------------------------------------


def _settings_path() -> Path:
    """Resolve the canonical settings.json path.

    Search order:
    1. ``APP_ROOT`` environment variable (if set)
    2. Current working directory
    3. ``~/.grinta/`` user-level config directory (global fallback)

    For *writing*, we always use location 1/2 (the explicit root or CWD).
    """
    # Explicit root override
    explicit_root = os.environ.get('APP_ROOT')
    if explicit_root:
        candidate = Path(explicit_root) / 'settings.json'
        if candidate.exists():
            return candidate

    # CWD
    cwd_candidate = Path.cwd() / 'settings.json'
    if cwd_candidate.exists():
        return cwd_candidate

    # User-level fallback (~/.grinta/settings.json)
    user_candidate = Path.home() / '.grinta' / 'settings.json'
    if user_candidate.exists():
        return user_candidate

    # Nothing found — default to CWD for creation
    if explicit_root:
        return Path(explicit_root) / 'settings.json'
    return cwd_candidate


def _load_raw_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _save_raw_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Onboarding — first-run API key collection
# ---------------------------------------------------------------------------


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
        return _DEFAULT_ONBOARDING_MODEL
    return _DEFAULT_MODEL_BY_PROVIDER.get(provider, _DEFAULT_ONBOARDING_MODEL)


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

    inferred_model = _default_model_from_environment()
    if not inferred_model:
        return None
    llm_cfg.model = inferred_model
    return inferred_model


def run_onboarding() -> AppConfig:
    """Interactive first-run: Provider → Model → API Key, persist, return config."""
    if not os.isatty(0):
        _console.print(
            '[red]No API key configured and stdin is not interactive.[/red]\n'
            'Run [bold]grinta[/bold] interactively first to complete setup,\n'
            'or place a settings.json with your key in the project directory\n'
            'or [bold]~/.grinta/settings.json[/bold].'
        )
        raise SystemExit(1)

    _console.print()
    _console.print(
        Panel(
            Text.from_markup(
                '[bold cyan]Welcome to Grinta[/bold cyan]\n\n'
                'Let\'s configure your LLM provider.\n\n'
                '[dim]Your settings are stored locally in settings.json — never sent anywhere else.[/dim]'
            ),
            title='[bold]First-Run Setup[/bold]',
            border_style='bright_cyan',
            padding=(1, 4),
        ),
        justify='center',
    )
    _console.print()

    # ── Step 1: Select provider ──
    _console.print('[bold]Step 1:[/bold] Choose your LLM provider\n')
    for i, (_, label) in enumerate(_ONBOARDING_PROVIDERS, 1):
        _console.print(f'  [cyan]{i:>2}[/cyan]  {label}')
    _console.print(f'  [cyan]{len(_ONBOARDING_PROVIDERS) + 1:>2}[/cyan]  [dim]Custom (OpenAI-compatible endpoint)[/dim]')
    _console.print()

    provider_key: str | None = None
    base_url: str | None = None
    custom_provider_name: str | None = None

    while True:
        choice = Prompt.ask(
            '[bold]Provider number[/bold]',
            console=_console,
        ).strip()
        try:
            idx = int(choice)
        except ValueError:
            _console.print('[red]  Enter a number from the list above.[/red]')
            continue

        if 1 <= idx <= len(_ONBOARDING_PROVIDERS):
            provider_key, _ = _ONBOARDING_PROVIDERS[idx - 1]
            break
        elif idx == len(_ONBOARDING_PROVIDERS) + 1:
            provider_key = 'custom'
            break
        else:
            _console.print('[red]  Enter a number from the list above.[/red]')

    _console.print()

    # ── Custom provider details ──
    if provider_key == 'custom':
        _console.print('[bold]Custom Provider Configuration[/bold]\n')
        custom_provider_name = Prompt.ask(
            '  Provider name [dim](e.g. together, fireworks)[/dim]',
            console=_console,
        ).strip()

        base_url = Prompt.ask(
            '  Base URL [dim](OpenAI-compatible, e.g. https://api.together.xyz/v1)[/dim]',
            console=_console,
        ).strip()
        if not base_url:
            _console.print('[red]  Base URL is required for custom providers.[/red]')
            raise SystemExit(1)

        model = Prompt.ask(
            '  Model name [dim](e.g. meta-llama/Llama-3-70b-chat-hf)[/dim]',
            console=_console,
        ).strip()
        if not model:
            _console.print('[red]  Model name is required.[/red]')
            raise SystemExit(1)

        _console.print()
        api_key = Prompt.ask(
            '  [bold]API Key[/bold]',
            console=_console,
        ).strip()

        # For custom provider, prefix with provider name if given
        if custom_provider_name:
            full_model = f'{custom_provider_name}/{model}' if '/' not in model else model
        else:
            full_model = model

    else:
        # ── Step 2: Model name ──
        default_model = _DEFAULT_MODEL_BY_PROVIDER.get(provider_key, '')
        hint = f' [dim](default: {default_model})[/dim]' if default_model else ''
        _console.print(f'[bold]Step 2:[/bold] Enter the model name{hint}\n')

        model_input = Prompt.ask(
            '  [bold]Model[/bold]',
            default=default_model or None,
            console=_console,
        ).strip()

        if not model_input:
            if default_model:
                model_input = default_model
            else:
                _console.print('[red]  Model name is required.[/red]')
                raise SystemExit(1)

        # Ensure model has provider prefix
        if '/' not in model_input:
            full_model = f'{provider_key}/{model_input}'
        else:
            full_model = model_input

        _console.print()

        # ── Step 3: API Key ──
        local_providers = {'ollama', 'lm_studio', 'vllm'}
        if provider_key in local_providers:
            _console.print('[dim]  Local provider — no API key needed (press Enter to skip).[/dim]')
            api_key = Prompt.ask(
                '  [bold]API Key[/bold] [dim](optional)[/dim]',
                default='',
                console=_console,
            ).strip()
        else:
            _console.print('[bold]Step 3:[/bold] Enter your API key\n')
            api_key = Prompt.ask(
                '  [bold]API Key[/bold]',
                console=_console,
            ).strip()

    # ── Persist ──
    settings = _load_raw_settings()
    settings['llm_model'] = full_model
    settings['llm_api_key'] = api_key
    if provider_key and provider_key != 'custom':
        settings['llm_provider'] = provider_key
    elif custom_provider_name:
        settings['llm_provider'] = custom_provider_name
    if base_url:
        settings['llm_base_url'] = base_url
    _save_raw_settings(settings)

    _console.print()
    _console.print(
        Panel(
            f'[green]✓ Configuration saved.[/green]\n'
            f'  Provider: [bold]{custom_provider_name or provider_key}[/bold]\n'
            f'  Model:    [bold]{full_model}[/bold]',
            border_style='green',
        ),
        justify='center',
    )
    _console.print()

    return load_app_config()


# ---------------------------------------------------------------------------
# Programmatic helpers for settings TUI
# ---------------------------------------------------------------------------


def get_current_model(config: AppConfig) -> str:
    try:
        return config.get_llm_config().model or '(not set)'
    except Exception:
        logger.debug('Could not read current model from config', exc_info=True)
        return '(not set)'


def _resolve_api_key_value(config: AppConfig) -> str | None:
    llm_cfg = config.get_llm_config()
    api_key: Any = getattr(llm_cfg, 'api_key', None)
    if api_key is not None:
        try:
            raw = api_key.get_secret_value()
        except AttributeError:
            raw = str(api_key)
        raw = raw.strip()
        if raw:
            return raw

    model = (getattr(llm_cfg, 'model', '') or '').strip()
    if model:
        try:
            from backend.core.config.api_key_manager import api_key_manager

            provider = api_key_manager.extract_provider(model)
            env_key = api_key_manager.get_provider_key_from_env(provider)
            if env_key and env_key.strip():
                return env_key.strip()
        except Exception:
            logger.debug('Could not resolve env-backed API key', exc_info=True)

    fallback = (os.environ.get('LLM_API_KEY') or '').strip()
    return fallback or None


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


def get_masked_api_key(config: AppConfig) -> str:
    try:
        raw = _resolve_api_key_value(config)
        if not raw:
            return '(not set)'
        return _mask_secret(raw)
    except Exception:
        logger.debug('Could not read API key for masking', exc_info=True)
        return '(not set)'


def update_model(model: str, provider: str | None = None, base_url: str | None = None) -> None:
    settings = _load_raw_settings()
    settings['llm_model'] = model
    if provider:
        settings['llm_provider'] = provider
    if base_url:
        settings['llm_base_url'] = base_url
    _save_raw_settings(settings)


def update_api_key(key: str) -> None:
    settings = _load_raw_settings()
    settings['llm_api_key'] = key
    _save_raw_settings(settings)


def update_budget(budget: float) -> None:
    settings = _load_raw_settings()
    settings['max_budget_per_task'] = budget
    _save_raw_settings(settings)


def get_budget(config: AppConfig) -> str:
    budget = getattr(config, 'max_budget_per_task', None)
    if budget is None:
        return 'unlimited'
    return f'${budget:.2f}'


def get_mcp_servers(config: AppConfig) -> list[dict[str, Any]]:
    try:
        if config.mcp and config.mcp.servers:
            return [
                {
                    'name': s.name,
                    'type': s.type,
                    'url': getattr(s, 'url', None),
                    'command': getattr(s, 'command', None),
                }
                for s in config.mcp.servers
            ]
    except Exception:
        logger.debug('Could not read MCP server list', exc_info=True)
    return []


def add_mcp_server(
    name: str, *, url: str | None = None, command: str | None = None
) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config', {})
    servers = mcp_cfg.get('servers', [])

    entry: dict[str, Any] = {'name': name}
    if url:
        entry['type'] = 'sse'
        entry['url'] = url
    elif command:
        import shlex

        parts = shlex.split(command)
        entry['type'] = 'stdio'
        entry['command'] = parts[0]
        entry['args'] = parts[1:]
    else:
        raise ValueError('Specify either url or command')

    servers.append(entry)
    mcp_cfg['servers'] = servers
    settings['mcp_config'] = mcp_cfg
    _save_raw_settings(settings)
