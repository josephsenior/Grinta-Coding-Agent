"""First-run interactive wizard for ``grinta init``.

Goal: zero-friction setup. Detect local model servers (Ollama, LM Studio),
prompt the user for a provider + key, write a valid ``settings.json``.

Re-runnable: existing settings are shown and the user can keep them.

Cross-platform reliability:
- Graceful network timeouts for local provider detection
- Proper directory creation with permissions checks
- Atomic file writes to prevent corruption
- Clear error messages for common failures
"""

from __future__ import annotations

import json
import os
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from backend.cli.config_manager import DEFAULT_MODEL_BY_PROVIDER
from backend.cli.theme import (
    CLR_BRAND,
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_META,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    no_color_enabled,
)
from backend.core.app_paths import get_canonical_settings_path
from backend.core.config.dotenv_keys import persist_llm_api_key_to_dotenv
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER

_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    'openai': {
        'env': 'OPENAI_API_KEY',
        'default_model': DEFAULT_MODEL_BY_PROVIDER['openai'],
        'base_url': '',
        'help': 'OpenAI / compatible (gpt-4o, gpt-5.x, ...)',
    },
    'anthropic': {
        'env': 'ANTHROPIC_API_KEY',
        'default_model': DEFAULT_MODEL_BY_PROVIDER['anthropic'],
        'base_url': '',
        'help': 'Anthropic (claude-sonnet-4-6, claude-opus-4-7, claude-haiku-4-5, ...)',
    },
    'google': {
        'env': 'GEMINI_API_KEY',
        'default_model': DEFAULT_MODEL_BY_PROVIDER['google'],
        'base_url': '',
        'help': 'Google Gemini (gemini-2.5-pro, gemini-3-flash, ...)',
    },
    'ollama': {
        'env': '',
        'default_model': 'ollama/llama3.2',
        'base_url': 'http://localhost:11434',
        'help': 'Local Ollama server (any pulled model)',
    },
    'lmstudio': {
        'env': '',
        'default_model': 'openai/local-model',
        'base_url': 'http://localhost:1234/v1',
        'help': 'Local LM Studio (OpenAI-compatible at /v1)',
    },
    'openrouter': {
        'env': 'OPENROUTER_API_KEY',
        'default_model': DEFAULT_MODEL_BY_PROVIDER['openrouter'],
        'base_url': 'https://openrouter.ai/api/v1',
        'help': 'OpenRouter (proxy to many providers)',
    },
}


def _get_platform_info() -> str:
    """Get platform string for error messages."""
    system = platform.system()
    if system == 'Windows':
        return 'Windows'
    elif system == 'Darwin':
        return 'macOS'
    elif system == 'Linux':
        return 'Linux'
    return f'{system} ({platform.release()})'


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    """Best-effort liveness probe; only http/https URLs are accepted.

    Args:
        url: The URL to probe
        timeout: Connection timeout in seconds (default 1.0 for faster detection)

    Returns:
        True if the URL responds with HTTP 2xx, False otherwise.
    """
    if not (url.startswith('http://') or url.startswith('https://')):
        return False
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', f'Grinta-init/{sys.version_info[:2]}')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 300
    except urllib.error.URLError:
        return False
    except Exception:
        return False


def _ollama_running(base_url: str) -> bool:
    """Check if Ollama server is running."""
    return _http_ok(f'{base_url}/api/tags')


def _lmstudio_running(base_url: str) -> bool:
    """Check if LM Studio server is running."""
    return _http_ok(f'{base_url}/models')


def _detect_local() -> list[str]:
    """Detect locally running model servers (Ollama, LM Studio).

    Returns list of detected providers. Empty list if no local servers found.
    This is a best-effort detection and should not block setup.
    """
    found: list[str] = []

    try:
        if _ollama_running(_PROVIDER_PRESETS['ollama']['base_url']):
            found.append('ollama')
    except Exception:
        pass

    try:
        if _lmstudio_running(_PROVIDER_PRESETS['lmstudio']['base_url']):
            found.append('lmstudio')
    except Exception:
        pass

    return found


def _check_settings_directory_writable(settings_path: Path) -> tuple[bool, str]:
    """Check if settings directory is writable, create if needed.

    Returns:
        (is_writable, error_message)
    """
    parent = settings_path.parent

    if parent.exists():
        if not os.access(parent, os.W_OK):
            return False, f'Settings directory exists but is not writable: {parent}'
        return True, ''

    try:
        parent.mkdir(parents=True, exist_ok=True)
        test_file = parent / '.write_test'
        test_file.write_text('test', encoding='utf-8')
        test_file.unlink()
        return True, ''
    except PermissionError:
        return False, f'Cannot create settings directory (permission denied): {parent}'
    except OSError as e:
        return False, f'Cannot create settings directory: {parent} ({e})'


def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically to prevent corruption on failure."""
    import tempfile

    content = json.dumps(data, indent=2) + '\n'
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix='.settings_', suffix='.tmp'
    )
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _settings_path(project_root: Path | None = None) -> Path:
    """Return the canonical settings path used by runtime config loading.

    ``project_root`` is accepted for backward compatibility with older callers;
    workspace selection is handled separately through ``PROJECT_ROOT`` / ``--project``.
    """
    del project_root
    return Path(get_canonical_settings_path())


def _load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _confirm_overwrite_existing(
    console: Console,
    existing: dict[str, Any],
) -> bool:
    cur_model = existing.get('llm_model', '(unset)')
    cur_provider = existing.get('llm_provider', '(unset)')
    console.print(
        f'[dim]Existing config:[/dim] provider=[bold]{cur_provider}[/bold]  model=[bold]{cur_model}[/bold]'
    )
    if not Confirm.ask('Overwrite existing settings?', default=False):
        console.print('[dim]No changes made.[/dim]')
        return False
    return True


def _print_provider_table(console: Console, detected: list[str]) -> None:
    table = Table(
        title='Pick a provider',
        title_style=CLR_CARD_TITLE,
        border_style=CLR_CARD_BORDER,
        box=box.ROUNDED,
        padding=(1, 2),
    )
    table.add_column('Key', style=CLR_BRAND)
    table.add_column('Description')
    table.add_column('Detected', style=CLR_STATUS_OK)
    for key, preset in _PROVIDER_PRESETS.items():
        detected_marker = '✓' if key in detected else ''
        table.add_row(key, preset['help'], detected_marker)
    console.print(table)


def _collect_api_key(console: Console, preset: dict[str, Any]) -> str:
    env_var = preset['env']
    if not env_var:
        # Local providers: usually no key required.
        return Prompt.ask('API key (optional)', password=True, default='')
    env_value = os.environ.get(env_var, '')
    if env_value:
        console.print(
            f'[dim]Found [bold]{env_var}[/bold] in environment — will reference it via [bold]${{{env_var}}}[/bold].[/dim]'
        )
        return f'${{{env_var}}}'
    api_key = Prompt.ask(
        f'API key (paste; or leave blank to set {env_var} later)',
        password=True,
        default='',
    )
    return api_key or f'${{{env_var}}}'


def run_init(project_root: Path | None = None, console: Console | None = None) -> int:
    """Run the wizard. Returns shell-style exit code.

    Exit codes:
        0 - Success
        1 - General error
        2 - Settings directory not writable
        3 - Invalid input
    """
    console = console or Console(no_color=no_color_enabled())
    platform_info = _get_platform_info()

    console.print(
        Panel.fit(
            f'[bold]Welcome to Grinta.[/bold] ({platform_info})\n'
            'This wizard configures your LLM provider and writes [bold]settings.json[/bold].\n'
            'API keys are stored in a sibling [bold].env[/bold] file when provided.\n'
            f'Re-run any time with [{CLR_BRAND}]grinta init[/].',
            border_style=CLR_CARD_BORDER,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )

    project_root = (project_root or Path.cwd()).resolve()
    settings_file = _settings_path()
    existing = _load_existing(settings_file)

    can_write, write_error = _check_settings_directory_writable(settings_file)
    if not can_write:
        console.print(
            f'[{CLR_STATUS_WARN}]Warning:[/] {write_error}', style=CLR_STATUS_WARN
        )
        console.print(
            f'[{CLR_META}]Tip: Set APP_ROOT environment variable to a writable directory.\n'
            f'  Example: APP_ROOT=~/.grinta grinta init[/]'
        )
        return 2

    if existing and not _confirm_overwrite_existing(console, existing):
        return 0

    console.print(f'[{CLR_META}]Detecting local model servers...[/]', end='')
    detected = _detect_local()
    console.print(' done.')
    if detected:
        console.print(f'[{CLR_STATUS_OK}]Found local:[/] {", ".join(detected)}')

    _print_provider_table(console, detected)

    provider = Prompt.ask(
        'Provider',
        choices=list(_PROVIDER_PRESETS.keys()),
        default=detected[0] if detected else 'openai',
    )
    preset = _PROVIDER_PRESETS[provider]
    model = Prompt.ask(
        'Model id (provider/model)',
        default=preset['default_model'],
    )

    if not model or not model.strip():
        console.print(
            f'[{CLR_STATUS_WARN}]Error:[/] Model cannot be empty.',
            style=CLR_STATUS_WARN,
        )
        return 3

    api_key = _collect_api_key(console, preset)
    base_url = Prompt.ask(
        'Base URL (leave blank for default)',
        default=preset['base_url'],
    )

    settings = {
        'llm_provider': provider,
        'llm_model': model,
        'llm_api_key': LLM_API_KEY_SETTINGS_PLACEHOLDER if api_key else '',
        'llm_base_url': base_url,
    }

    try:
        _atomic_json_write(settings_file, settings)
    except PermissionError:
        console.print(
            f'[{CLR_STATUS_WARN}]Error:[/] Cannot write to {settings_file}',
            style=CLR_STATUS_WARN,
        )
        return 2
    except Exception as e:
        console.print(
            f'[{CLR_STATUS_WARN}]Error:[/] Failed to write settings: {e}',
            style=CLR_STATUS_WARN,
        )
        return 1

    if api_key:
        try:
            persist_llm_api_key_to_dotenv(api_key, settings_json_path=settings_file)
        except PermissionError:
            console.print(
                f'[{CLR_STATUS_WARN}]Warning:[/] Could not write .env file. '
                'API key will need to be set via environment variable.',
                style=CLR_STATUS_WARN,
            )
        except Exception as e:
            console.print(
                f'[{CLR_STATUS_WARN}]Warning:[/] Could not persist API key: {e}',
                style=CLR_STATUS_WARN,
            )

    global_dir = Path.home() / '.grinta'
    is_global = False
    try:
        if settings_file.is_relative_to(global_dir):
            is_global = True
    except Exception:
        pass

    scope_note = ''
    if not is_global:
        scope_note = f'[{CLR_STATUS_WARN}]Note: Running from source. Settings localized to this directory.[/]\n'

    console.print(
        Panel.fit(
            f'Wrote [bold]{settings_file}[/bold]\n'
            f'{scope_note}'
            f'Provider: [bold]{provider}[/bold]\n'
            f'Model: [bold]{model}[/bold]\n\n'
            f'Start the agent with: [{CLR_BRAND}]grinta[/]\n'
            f'REPL commands: [{CLR_BRAND}]/help[/] · shell commands: [{CLR_BRAND}]grinta sessions ...[/]',
            title='Setup complete',
            border_style=CLR_STATUS_OK,
        )
    )

    checklist = project_root / 'docs' / 'SECURITY_CHECKLIST.md'
    if checklist.exists():
        console.print(
            f'[{CLR_META}]Tip: read [bold]docs/SECURITY_CHECKLIST.md[/bold] '
            'before pointing Grinta at untrusted code.[/]'
        )

    return 0


__all__ = ['run_init']
