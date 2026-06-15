"""LSP (code intelligence) renderer with symbol info display."""

from __future__ import annotations

from typing import Any

from backend.cli.display.transcript import format_activity_primary
from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_SECONDARY,
)


def render_lsp_query(
    command: str,
    target: str = '',
    location: str = '',
    definition: str = '',
    references: list[str] | None = None,
) -> list[Any]:
    """Render an LSP query result."""
    lines: list[Any] = []

    lines.append(format_activity_primary(command.title(), target))

    if location:
        lines.append(f'  [dim]{location}[/dim]')

    if definition:
        lines.append('')
        lines.append(f'  [{CLR_BRAND_HUE}]{definition}[/{CLR_BRAND_HUE}]')

    if references:
        lines.append('')
        lines.append(f'  [{CLR_SECONDARY}]References ({len(references)}):[/]')
        for ref in references[:5]:
            lines.append(f'    [dim]· {ref}[/dim]')
        if len(references) > 5:
            lines.append(f'    [dim]... {len(references) - 5} more[/dim]')

    return lines
