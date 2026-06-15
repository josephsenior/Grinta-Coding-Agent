"""Browser tool renderer with navigation/action display."""

from __future__ import annotations

from typing import Any

from rich.markup import escape as markup_escape

from backend.cli.display.transcript import format_activity_primary


def render_browser_navigation(
    action: str,
    url: str = '',
    title: str = '',
    steps: list[str] | None = None,
) -> list[Any]:
    """Render a browser action."""
    lines: list[Any] = []

    action_verb = action.replace('_', ' ').title()
    lines.append(format_activity_primary(action_verb, url or 'Browser'))

    if title:
        # Escape title to prevent MarkupError
        escaped_title = markup_escape(title)
        lines.append(f'  [dim]{escaped_title}[/dim]')

    if steps:
        lines.append('')
        for i, step in enumerate(steps[:5], 1):
            # Escape step to prevent MarkupError
            escaped_step = markup_escape(step)
            lines.append(f'  [dim]{i}. {escaped_step}[/dim]')
        if len(steps) > 5:
            lines.append(f'  [dim]... {len(steps) - 5} more steps[/dim]')

    return lines


def render_browser_page(
    url: str,
    title: str = '',
    content_preview: str = '',
) -> list[Any]:
    """Render a loaded page."""
    lines: list[Any] = []

    lines.append(format_activity_primary('Loaded', url))

    if title:
        # Escape title to prevent MarkupError
        escaped_title = markup_escape(title)
        lines.append(f'  [dim]{escaped_title}[/dim]')

    if content_preview:
        lines.append('')
        preview_lines = content_preview.splitlines()[:4]
        for line in preview_lines:
            stripped = line.strip()
            if stripped:
                if len(stripped) > 100:
                    stripped = stripped[:97] + '…'
                # Escape content to prevent MarkupError
                escaped = markup_escape(stripped)
                lines.append(f'  [dim]{escaped}[/dim]')

    return lines
