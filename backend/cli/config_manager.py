"""Configuration management — onboarding, settings I/O, API key handling."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from backend.core.config import AppConfig, load_app_config

logger = logging.getLogger(__name__)

_console = Console()
_DEFAULT_ONBOARDING_MODEL = 'openai/gpt-4.1'
_DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    'anthropic': 'anthropic/claude-sonnet-4-20250514',
    'google': 'google/gemini-2.5-flash',
    'groq': 'groq/meta-llama/llama-4-scout',
    'lightning': 'lightning/meta-llama/Meta-Llama-3.1-8B-Instruct',
    'openai': _DEFAULT_ONBOARDING_MODEL,
    'openrouter': 'openrouter/anthropic/claude-3.5-sonnet',
    'xai': 'xai/grok-4.1-fast',
    'deepseek': 'deepseek/deepseek-chat',
}

# Provider registry — grouped for clean onboarding display.
# (key, display_label, category)
_PROVIDERS: list[tuple[str, str, str]] = [
    # ── Cloud providers (most popular first) ──
    ('openai', 'OpenAI', 'cloud'),
    ('anthropic', 'Anthropic', 'cloud'),
    ('google', 'Google Gemini', 'cloud'),
    ('groq', 'Groq', 'cloud'),
    ('xai', 'xAI (Grok)', 'cloud'),
    ('deepseek', 'DeepSeek', 'cloud'),
    # ── Aggregators / proxies ──
    ('openrouter', 'OpenRouter', 'aggregator'),
    ('lightning', 'Lightning AI', 'aggregator'),
    ('nvidia', 'NVIDIA NIM', 'aggregator'),
    # ── Local providers ──
    ('ollama', 'Ollama', 'local'),
    ('lm_studio', 'LM Studio', 'local'),
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

    env_model = _default_model_from_environment()
    if not env_model:
        return None
    llm_cfg.model = env_model
    return env_model


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

        # Found a key — set it in the config
        llm_cfg.api_key = SecretStr(env_key)
        if not (getattr(llm_cfg, 'model', None) or '').strip():
            llm_cfg.model = _default_model_for_provider(provider)
        logger.info('Auto-detected API key from %s for provider %s', env_var, provider)
        return provider

    return None


def run_onboarding() -> AppConfig:
    """Interactive first-run setup. Clean, minimal, validates before saving."""
    if not os.isatty(0):
        _console.print(
            '[red]No API key configured and stdin is not interactive.[/red]\n'
            'Run [bold]grinta[/bold] in a terminal to complete setup,\n'
            'or create [bold]~/.grinta/settings.json[/bold] with your config.'
        )
        raise SystemExit(1)

    _console.print()
    _console.print(
        Panel(
            Text.from_markup(
                '[bold cyan]Welcome to Grinta[/bold cyan]\n\n'
                "Let's get you connected to an LLM.\n"
                '[dim]Settings saved locally — never sent anywhere.[/dim]'
            ),
            border_style='dim',
            padding=(1, 3),
        ),
    )
    _console.print()

    # ── Provider selection ──
    provider_key, base_url, custom_provider_name = _select_provider()

    # ── Model selection ──
    full_model = _select_model(provider_key, custom_provider_name)

    # ── API key ──
    api_key = _collect_api_key(provider_key)

    # ── Validate connection ──
    _validate_connection(full_model, api_key, base_url)

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
            Text.from_markup(
                '[green bold]✓ Ready to go![/green bold]\n\n'
                f'  Provider  [bold]{custom_provider_name or provider_key}[/bold]\n'
                f'  Model     [bold]{full_model}[/bold]\n\n'
                '[dim]Change anytime with [bold]/settings[/bold][/dim]'
            ),
            border_style='green',
            padding=(1, 3),
        ),
    )
    _console.print()

    return load_app_config()


def _select_provider() -> tuple[str, str | None, str | None]:
    """Provider picker. Returns (provider_key, base_url, custom_name)."""
    _console.print('[bold]Choose your LLM provider[/bold]\n')

    # Group by category
    cloud = [(k, l) for k, l, c in _PROVIDERS if c == 'cloud']
    aggregator = [(k, l) for k, l, c in _PROVIDERS if c == 'aggregator']
    local = [(k, l) for k, l, c in _PROVIDERS if c == 'local']

    idx = 1
    provider_map: dict[int, tuple[str, str]] = {}

    for key, label in cloud:
        marker = ' [dim](recommended)[/dim]' if key in ('openai', 'anthropic') else ''
        _console.print(f'  [cyan]{idx:>2}[/cyan]  {label}{marker}')
        provider_map[idx] = (key, label)
        idx += 1

    _console.print()
    for key, label in aggregator:
        _console.print(f'  [cyan]{idx:>2}[/cyan]  [dim]{label}[/dim]')
        provider_map[idx] = (key, label)
        idx += 1

    _console.print()
    for key, label in local:
        _console.print(f'  [cyan]{idx:>2}[/cyan]  {label} [dim](local)[/dim]')
        provider_map[idx] = (key, label)
        idx += 1

    custom_idx = idx
    _console.print(f'\n  [cyan]{custom_idx:>2}[/cyan]  [dim]Custom endpoint[/dim]')
    _console.print()

    while True:
        choice = Prompt.ask('[bold]Provider[/bold]', console=_console).strip()
        try:
            num = int(choice)
        except ValueError:
            _console.print('[red]  Enter a number from the list.[/red]')
            continue

        if num in provider_map:
            provider_key, _ = provider_map[num]
            return provider_key, None, None
        elif num == custom_idx:
            return _collect_custom_provider()
        else:
            _console.print('[red]  Enter a number from the list.[/red]')


def _collect_custom_provider() -> tuple[str, str | None, str | None]:
    """Collect custom OpenAI-compatible provider details."""
    _console.print('\n[bold]Custom Provider[/bold]\n')

    name = Prompt.ask(
        '  Name [dim](e.g. together, fireworks)[/dim]',
        console=_console,
    ).strip()

    base_url = Prompt.ask(
        '  Base URL [dim](e.g. https://api.together.xyz/v1)[/dim]',
        console=_console,
    ).strip()
    if not base_url:
        _console.print('[red]  Base URL is required.[/red]')
        raise SystemExit(1)

    return 'custom', base_url, name or 'custom'


def _select_model(provider_key: str, custom_name: str | None = None) -> str:
    """Model selection with smart defaults."""
    _console.print()

    default = _DEFAULT_MODEL_BY_PROVIDER.get(provider_key, '')
    if default:
        _console.print(f'[bold]Model[/bold] [dim](Enter for {default})[/dim]\n')
    else:
        _console.print('[bold]Model[/bold] [dim](e.g. provider/model-name)[/dim]\n')

    model_input = (
        Prompt.ask(
            '  Model',
            default=default or None,
            console=_console,
        )
        or ''
    ).strip()

    if not model_input:
        if default:
            model_input = default
        else:
            _console.print('[red]  Model name is required.[/red]')
            raise SystemExit(1)

    # Ensure provider prefix
    if '/' not in model_input:
        prefix = custom_name or provider_key
        return f'{prefix}/{model_input}'
    return model_input


def _collect_api_key(provider_key: str) -> str:
    """Collect API key with password masking. Skip for local providers."""
    _console.print()

    local_providers = {'ollama', 'lm_studio', 'vllm'}
    if provider_key in local_providers:
        _console.print('[dim]  Local provider — no API key needed.[/dim]')
        key = Prompt.ask(
            '  API Key [dim](Enter to skip)[/dim]',
            default='',
            console=_console,
            password=True,
        ).strip()
        return key

    _console.print('[bold]API Key[/bold]\n')
    while True:
        key = Prompt.ask('  Key', console=_console, password=True).strip()
        if key:
            return key
        _console.print('[red]  API key is required for this provider.[/red]')


def _validate_connection(model: str, api_key: str, base_url: str | None) -> None:
    """Test the LLM connection with a minimal request. Non-fatal on failure."""
    if not api_key:
        return

    from rich.spinner import Spinner
    from rich.live import Live

    spinner = Spinner('dots', text='  Validating connection…', style='cyan')
    try:
        with Live(spinner, console=_console, transient=True):
            import asyncio
            result = asyncio.run(_test_llm_call(model, api_key, base_url))

        if result is True:
            _console.print('  [green]✓[/green] Connection verified')
        elif isinstance(result, str):
            _console.print(f'  [yellow]⚠[/yellow] [dim]{result}[/dim]')
            _console.print('  [dim]Settings saved anyway — you can fix this in /settings[/dim]')
    except Exception:
        _console.print('  [dim]⚠ Could not verify (will try when you send a message)[/dim]')


async def _test_llm_call(model: str, api_key: str, base_url: str | None) -> bool | str:
    """Make a minimal LLM call to verify credentials. Returns True or error string."""
    import httpx

    # Determine the API endpoint from the model prefix
    provider = model.split('/')[0] if '/' in model else ''
    url = base_url or _provider_base_url(provider)
    if not url:
        return 'Unknown provider — skipping validation'

    # Normalize URL
    url = url.rstrip('/')
    if not url.endswith('/v1'):
        url = f'{url}/v1'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }

    # Strip provider prefix for the API call
    api_model = model
    if '/' in model:
        parts = model.split('/', 1)
        # Keep compound model names (e.g. meta-llama/Llama-3), strip simple provider prefix
        if parts[0] in ('openai', 'anthropic', 'google', 'groq', 'xai', 'deepseek'):
            api_model = parts[1]

    body = {
        'model': api_model,
        'messages': [{'role': 'user', 'content': 'Say "ok" and nothing else.'}],
        'max_tokens': 5,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f'{url}/chat/completions', json=body, headers=headers)
            if resp.status_code == 200:
                return True
            elif resp.status_code == 401:
                return 'Invalid API key (401 Unauthorized)'
            elif resp.status_code == 404:
                return f'Model not found: {api_model}'
            elif resp.status_code == 429:
                return 'Rate limited — but credentials look valid'
            else:
                return f'API returned {resp.status_code}'
    except httpx.TimeoutException:
        return 'Connection timed out — check your network'
    except httpx.ConnectError:
        return 'Could not connect — check the base URL'
    except Exception as e:
        return f'Connection error: {type(e).__name__}'


def _provider_base_url(provider: str) -> str | None:
    """Map provider key to base API URL for validation."""
    urls: dict[str, str] = {
        'openai': 'https://api.openai.com',
        'groq': 'https://api.groq.com/openai',
        'xai': 'https://api.x.ai',
        'deepseek': 'https://api.deepseek.com',
        'openrouter': 'https://openrouter.ai/api',
        'lightning': 'https://lightning.ai/api',
        'nvidia': 'https://integrate.api.nvidia.com',
    }
    return urls.get(provider)


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
