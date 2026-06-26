"""Numbered menu prompts shared by onboarding and settings flows."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.prompt import Prompt

from backend.cli.theme import CLR_BRAND, CLR_META, CLR_STATUS_ERR

_MORE_PROVIDERS = '__more_providers__'


def prompt_numbered_choice(
    console: Console,
    *,
    title: str,
    items: Sequence[tuple[str, str]],
    cancel_label: str = 'Cancel',
    default_index: int | None = None,
) -> str | None:
    """Render a numbered menu and return the selected item key."""
    if not items:
        return None

    console.print()
    console.print(f'[bold]{title}[/bold]')
    for idx, (_key, label) in enumerate(items, 1):
        console.print(f'  [{CLR_BRAND}]{idx:>2}[/]  {label}')

    default_hint = ''
    if default_index is not None and 1 <= default_index <= len(items):
        default_hint = f' [{CLR_META}](default: {default_index})[/]'

    choice = Prompt.ask(
        f'  Number{default_hint} [dim](Enter to cancel)[/dim]',
        default=str(default_index) if default_index is not None else '',
        console=console,
    ).strip()
    if not choice:
        return None
    try:
        selected = int(choice)
    except ValueError:
        console.print(f'[{CLR_STATUS_ERR}]  Not a number: {choice!r}[/]')
        return None
    if not 1 <= selected <= len(items):
        console.print(f'[{CLR_STATUS_ERR}]  Invalid selection: {selected}[/]')
        return None
    return items[selected - 1][0]


def format_detected_model_preview(models: Sequence[str], *, limit: int = 4) -> str:
    """Compact model list for detected local providers."""
    if not models:
        return 'running (no models listed)'
    preview = ', '.join(models[:limit])
    if len(models) > limit:
        preview += f' (+{len(models) - limit} more)'
    return preview


def more_providers_menu_key() -> str:
    return _MORE_PROVIDERS


def is_more_providers_menu_key(key: str) -> bool:
    return key == _MORE_PROVIDERS


__all__ = [
    'format_detected_model_preview',
    'is_more_providers_menu_key',
    'more_providers_menu_key',
    'prompt_numbered_choice',
]
