"""Browser tool renderer with navigation/action display."""

from __future__ import annotations

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    CLR_DETAIL,
    CLR_SECONDARY,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    CLR_BRAND_HUE,
)
from backend.cli.transcript import format_activity_primary


def render_browser_navigation(
    action: str,
    url: str = '',
    title: str = '',
    steps: list[str] | None = None,
) -> list[str]:
    """Render a browser navigation/interaction."""
    lines: list[str] = []

    badge = badge_for_tool_name('browser')

    action_verb = action.replace('_', ' ').title()
    lines.append(format_activity_primary(action_verb, url or 'Browser'))

    if title:
        lines.append(f"  [dim]{title}[/dim]")

    if steps:
        lines.append('')
        for i, step in enumerate(steps[:5], 1):
            lines.append(f"  [dim]{i}. {step}[/dim]")
        if len(steps) > 5:
            lines.append(f"  [dim]... {len(steps) - 5} more steps[/dim]")

    return lines


def render_browser_page(
    url: str,
    title: str = '',
    content_preview: str = '',
) -> list[str]:
    """Render a loaded page."""
    lines: list[str] = []

    lines.append(format_activity_primary('Loaded', url))

    if title:
        lines.append(f"  [dim]{title}[/dim]")

    if content_preview:
        lines.append('')
        preview_lines = content_preview.splitlines()[:4]
        for line in preview_lines:
            stripped = line.strip()
            if stripped:
                if len(stripped) > 100:
                    stripped = stripped[:97] + '…'
                lines.append(f"  [dim]{stripped}[/dim]")

    return lines