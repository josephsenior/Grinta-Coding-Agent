"""File editor renderer with structured diff display.

Shows file edits with badge, path info, and syntax-highlighted diff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.cli.theme import (
    CLR_DETAIL,
    CLR_SECONDARY,
    CLR_STATUS_OK,
    CLR_VERB,
)
from backend.cli.transcript import format_activity_primary, format_activity_delta_secondary

if TYPE_CHECKING:
    from rich.console import Console


def render_file_edit(
    verb: str,
    path: str,
    line_range: str = '',
    diff_lines: list[str] | None = None,
    added: int = 0,
    removed: int = 0,
    new_file: bool = False,
) -> list[str]:
    """Render a file edit with optional diff lines.

    Returns a list of Rich markup lines for console.print().
    """
    lines: list[str] = []

    # Build detail with inline stats for new files
    detail = path
    if new_file and added:
        detail += f"  [{CLR_STATUS_OK}]+{added}[/{CLR_STATUS_OK}]"
    elif line_range:
        detail = f"{path}  [dim]·  {line_range}[/dim]"

    # For edits (not new files), show delta as secondary line
    if not new_file and (added or removed):
        delta = format_activity_delta_secondary(added=added, removed=removed)
        if delta:
            lines.append(f"  {delta}")

    lines.append(format_activity_primary(verb, detail))

    if diff_lines:
        for line in diff_lines[:20]:
            stripped = line.rstrip()
            if stripped.startswith('+') and not stripped.startswith('+++'):
                lines.append(f"[{CLR_STATUS_OK}]{stripped}[/{CLR_STATUS_OK}]")
            elif stripped.startswith('-') and not stripped.startswith('---'):
                lines.append(f"[{CLR_DETAIL}]{stripped}[/{CLR_DETAIL}]")
            elif stripped.startswith('@@'):
                lines.append(f"[{CLR_SECONDARY}]{stripped}[/{CLR_SECONDARY}]")
            else:
                lines.append(f"[dim]{stripped}[/dim]")

        if len(diff_lines) > 20:
            lines.append(f"  [dim]... {len(diff_lines) - 20} more diff lines[/dim]")

    return lines


def render_file_read(
    path: str,
    line_range: str = '',
    line_count: int = 0,
) -> list[str]:
    """Render a file read event."""
    if line_range:
        detail = f"{path}  [dim]·  {line_range}[/dim]"
    elif line_count:
        detail = f"{path}  [dim]({line_count} lines)[/dim]"
    else:
        detail = path

    return [format_activity_primary('Read', detail)]


def render_file_create(
    path: str,
    line_count: int = 0,
) -> list[str]:
    """Render a new file creation."""
    detail = path
    if line_count:
        detail += f"  [{CLR_STATUS_OK}]+{line_count}[/{CLR_STATUS_OK}]"

    return [format_activity_primary('Created', detail)]