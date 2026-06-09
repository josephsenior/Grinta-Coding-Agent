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


def _format_file_detail(
    path: str,
    *,
    new_file: bool,
    added: int,
    line_range: str,
) -> str:
    if new_file and added:
        return f'{path}  [{CLR_STATUS_OK}]+{added}[/{CLR_STATUS_OK}]'
    if line_range:
        return f'{path}  [{NAVY_TEXT_DIM}]·  {line_range}[/]'
    return path


def _format_delta_line(added: int, removed: int) -> str:
    delta = format_activity_delta_secondary(added=added, removed=removed)
    return f'  {delta}' if delta else ''


def _needs_delta(new_file: bool, added: int, removed: int) -> bool:
    return not new_file and (added or removed)


def _needs_preview(new_file: bool, preview_content: str | None) -> bool:
    return new_file and preview_content


def _format_delta_or_preview(
    *,
    new_file: bool,
    added: int,
    removed: int,
    preview_content: str | None,
) -> list[Any]:
    if _needs_delta(new_file, added, removed):
        line = _format_delta_line(added, removed)
        return [line] if line else []
    if _needs_preview(new_file, preview_content):
        return _preview_lines(preview_content)
    return []


def _is_added_line(stripped: str) -> bool:
    return stripped.startswith('+') and not stripped.startswith('+++')


def _is_removed_line(stripped: str) -> bool:
    return stripped.startswith('-') and not stripped.startswith('---')


def _format_single_diff_line(stripped: str) -> str:
    if _is_added_line(stripped):
        content = markup_escape(stripped[1:])
        return f'[{CLR_STATUS_OK}]+{content}[/{CLR_STATUS_OK}]'
    if _is_removed_line(stripped):
        content = markup_escape(stripped[1:])
        return f'[{CLR_DETAIL}]-{content}[/{CLR_DETAIL}]'
    if stripped.startswith('@@'):
        return f'[{CLR_SECONDARY}]{stripped}[/{CLR_SECONDARY}]'
    escaped = markup_escape(stripped)
    return f'[dim]{escaped}[/dim]'


def _render_diff_block(diff_lines: list[str]) -> list[Any]:
    result: list[Any] = []
    for line in diff_lines[:20]:
        result.append(_format_single_diff_line(line.rstrip()))
    if len(diff_lines) > 20:
        result.append(f'  [dim]... {len(diff_lines) - 20} more diff lines[/dim]')
    return result


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

    detail = _format_file_detail(
        path, new_file=new_file, added=added, line_range=line_range,
    )
    lines.extend(_format_delta_or_preview(
        new_file=new_file, added=added, removed=removed,
        preview_content=preview_content,
    ))
    lines.append(format_activity_primary(verb, detail))

    if diff_lines:
        lines.extend(_render_diff_block(diff_lines))

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
