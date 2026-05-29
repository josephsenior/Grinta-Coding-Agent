"""File editor renderer with structured diff display.

Shows file edits with badge, path info, and syntax-highlighted diff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.markup import escape as markup_escape

from backend.cli.theme import (
    CLR_DETAIL,
    CLR_SECONDARY,
    CLR_STATUS_OK,
    NAVY_TEXT_DIM,
)
from backend.cli.transcript import (
    format_activity_delta_secondary,
    format_activity_primary,
)

if TYPE_CHECKING:
    pass


def _preview_lines(
    content: str,
    *,
    max_lines: int = 12,
    max_chars: int = 160,
) -> list[Any]:
    lines: list[Any] = []
    if not content:
        return lines
    raw_lines = content.splitlines()
    for line in raw_lines[:max_lines]:
        truncated = line[:max_chars] + ('...' if len(line) > max_chars else '')
        lines.append(f'  [dim]{markup_escape(truncated)}[/dim]')
    if len(raw_lines) > max_lines:
        lines.append(f'  [dim]... {len(raw_lines) - max_lines} more lines[/dim]')
    return lines


def render_file_edit(
    verb: str,
    path: str,
    line_range: str = '',
    diff_lines: list[str] | None = None,
    added: int = 0,
    removed: int = 0,
    new_file: bool = False,
    preview_content: str | None = None,
) -> list[Any]:
    """Render a file edit with optional diff lines.

    Returns a list of Rich markup lines for console.print().
    """
    lines: list[Any] = []

    # Build detail with inline stats for new files
    detail = path
    if new_file and added:
        detail += f'  [{CLR_STATUS_OK}]+{added}[/{CLR_STATUS_OK}]'
    elif line_range:
        detail = f'{path}  [{NAVY_TEXT_DIM}]·  {line_range}[/]'

    # For edits (not new files), show delta as secondary line

    if not new_file and (added or removed):
        delta = format_activity_delta_secondary(added=added, removed=removed)
        if delta:
            lines.append(f'  {delta}')
    elif new_file and preview_content:
        lines.extend(_preview_lines(preview_content))

    lines.append(format_activity_primary(verb, detail))

    if diff_lines:
        for line in diff_lines[:20]:
            stripped = line.rstrip()
            if stripped.startswith('+') and not stripped.startswith('+++'):
                # Escape content after the + sign to prevent MarkupError
                content = markup_escape(stripped[1:])
                lines.append(f'[{CLR_STATUS_OK}]+{content}[/{CLR_STATUS_OK}]')
            elif stripped.startswith('-') and not stripped.startswith('---'):
                # Escape content after the - sign to prevent MarkupError
                content = markup_escape(stripped[1:])
                lines.append(f'[{CLR_DETAIL}]-{content}[/{CLR_DETAIL}]')
            elif stripped.startswith('@@'):
                lines.append(f'[{CLR_SECONDARY}]{stripped}[/{CLR_SECONDARY}]')
            else:
                # Escape context lines to prevent MarkupError
                escaped = markup_escape(stripped)
                lines.append(f'[dim]{escaped}[/dim]')

        if len(diff_lines) > 20:
            lines.append(f'  [dim]... {len(diff_lines) - 20} more diff lines[/dim]')

    return lines


def render_file_read(
    path: str,
    line_range: str = '',
    line_count: int = 0,
) -> list[Any]:
    """Render a file read event."""
    if line_range:
        detail = f'{path}  [{NAVY_TEXT_DIM}]·  {line_range}[/]'
    elif line_count:
        detail = f'{path}  [{NAVY_TEXT_DIM}]({line_count} lines)[/]'
    else:
        detail = path

    return [format_activity_primary('Read', detail)]


def render_file_create(
    path: str,
    line_count: int = 0,
    preview_content: str | None = None,
) -> list[Any]:
    """Render a new file creation."""
    detail = path
    if line_count:
        detail += f'  [{CLR_STATUS_OK}]+{line_count}[/{CLR_STATUS_OK}]'

    lines = [format_activity_primary('Created', detail)]
    lines.extend(_preview_lines(preview_content or ''))
    return lines
