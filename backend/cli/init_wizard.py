"""First-run interactive wizard for ``grinta init``.

Goal: zero-friction setup. Detect local model servers (Ollama, LM Studio),
prompt the user for a provider + key, write a valid ``settings.json``.

Re-runnable: existing settings are shown and the user can keep them.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    'openai': {
        'env': 'OPENAI_API_KEY',
        'default_model': 'openai/gpt-4o-mini',
        'base_url': '',
        'help': 'OpenAI / compatible (gpt-4o, gpt-4.1, o1, o3, ...)',
    },
    'anthropic': {
        'env': 'ANTHROPIC_API_KEY',
        'default_model': 'anthropic/claude-sonnet-4-20250514',
        'base_url': '',
        'help': 'Anthropic (claude-sonnet-4, claude-opus-4, claude-haiku-4)',
    },
    'google': {
        'env': 'GEMINI_API_KEY',
        'default_model': 'google/gemini-2.5-pro',
        'base_url': '',
        'help': 'Google Gemini (gemini-2.5-pro, gemini-2.5-flash)',
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
        'default_model': 'openrouter/anthropic/claude-3.5-sonnet',
        'base_url': 'https://openrouter.ai/api/v1',
        'help': 'OpenRouter (proxy to many providers)',
    },
}


def _http_ok(url: str) -> bool:
    """Best-effort liveness probe; only http/https URLs are accepted."""
    if not (url.startswith('http://') or url.startswith('https://')):
        return False
    try:
        req = urllib.request.Request(url)  # noqa: S310 (scheme guarded above)
        with urllib.request.urlopen(req, timeout=0.5):  # noqa: S310
            return True
    except Exception:
        return False


def _ollama_running(base_url: str) -> bool:
    return _http_ok(f'{base_url}/api/tags')


def _lmstudio_running(base_url: str) -> bool:
    return _http_ok(f'{base_url}/models')


def _detect_local() -> list[str]:
    found: list[str] = []
    if _ollama_running(_PROVIDER_PRESETS['ollama']['base_url']):
        found.append('ollama')
    if _lmstudio_running(_PROVIDER_PRESETS['lmstudio']['base_url']):
        found.append('lmstudio')
    return found


def _settings_path(project_root: Path) -> Path:
    return project_root / 'settings.json'


def _load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def run_init(project_root: Path | None = None, console: Console | None = None) -> int:
    """Run the wizard. Returns shell-style exit code."""
    console = console or Console()
    project_root = (project_root or Path.cwd()).resolve()
    settings_file = _settings_path(project_root)
    existing = _load_existing(settings_file)

    console.print(
        Panel.fit(
            '[bold]Welcome to Grinta.[/bold]\n'
            'This wizard configures your LLM provider and writes [bold]settings.json[/bold].\n'
            'Re-run any time with [bold cyan]grinta init[/bold cyan].',
            border_style='cyan',
        )
    )

    if existing:
        cur_model = existing.get('llm_model', '(unset)')
        cur_provider = existing.get('llm_provider', '(unset)')
        console.print(
            f'[dim]Existing config:[/dim] provider=[bold]{cur_provider}[/bold]  model=[bold]{cur_model}[/bold]'
        )
        if not Confirm.ask('Overwrite existing settings?', default=False):
            console.print('[dim]No changes made.[/dim]')
            return 0

    # Detect local servers and surface them first.
    detected = _detect_local()
    if detected:
        console.print(
            f'[green]Detected local provider(s):[/green] {", ".join(detected)}'
        )

    # Render provider menu.
    table = Table(title='Pick a provider', border_style='dim')
    table.add_column('Key', style='bold cyan')
    table.add_column('Description')
    table.add_column('Detected', style='green')
    for key, preset in _PROVIDER_PRESETS.items():
        detected_marker = '✓' if key in detected else ''
        table.add_row(key, preset['help'], detected_marker)
    console.print(table)

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

    api_key = ''
    env_var = preset['env']
    if env_var:
        env_value = os.environ.get(env_var, '')
        if env_value:
            console.print(
                f'[dim]Found [bold]{env_var}[/bold] in environment — will reference it via [bold]${{{env_var}}}[/bold].[/dim]'
            )
            api_key = f'${{{env_var}}}'
        else:
            api_key = Prompt.ask(
                f'API key (paste; or leave blank to set {env_var} later)',
                password=True,
                default='',
            )
            if not api_key:
                api_key = f'${{{env_var}}}'
    else:
        # Local providers: usually no key required.
        api_key = Prompt.ask('API key (optional)', password=True, default='')

    base_url = Prompt.ask(
        'Base URL (leave blank for default)',
        default=preset['base_url'],
    )

    settings = {
        'llm_provider': provider,
        'llm_model': model,
        'llm_api_key': api_key,
        'llm_base_url': base_url,
    }

    settings_file.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
    console.print(
        Panel.fit(
            f'Wrote [bold]{settings_file}[/bold]\n'
            f'Provider: [bold]{provider}[/bold]\n'
            f'Model: [bold]{model}[/bold]\n\n'
            'Start the agent with: [bold cyan]grinta[/bold cyan]\n'
            'Slash commands inside the REPL: [bold cyan]/help[/bold cyan]',
            title='Setup complete',
            border_style='green',
        )
    )

    # Surface a security checklist link if it exists.
    checklist = project_root / 'docs' / 'SECURITY_CHECKLIST.md'
    if checklist.exists():
        console.print(
            '[dim]Tip: read [bold]docs/SECURITY_CHECKLIST.md[/bold] '
            'before pointing Grinta at untrusted code.[/dim]'
        )

    return 0


__all__ = ['run_init']
