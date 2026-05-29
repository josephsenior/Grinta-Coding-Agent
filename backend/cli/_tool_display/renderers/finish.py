"""Finish/completion renderer with summary stats.

Shows the final task summary with changed files, duration, and stats.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from backend.cli._tool_display.renderers._syntax import highlight_code_blocks
from backend.cli.theme import (
    CLR_DETAIL,
    CLR_SECONDARY,
    CLR_STATUS_OK,
)
from backend.cli.transcript import format_activity_primary


def render_finish_summary(
    summary: str | None = None,
    files_changed: int = 0,
    lines_added: int = 0,
    lines_removed: int = 0,
    duration: str = '',
    tool_calls: int = 0,
    files: list[str] | None = None,
) -> list[Any]:
    """Render finish/completion summary."""
    lines: list[Any] = []

    if summary:
        if '```' in summary:
            highlighted = highlight_code_blocks(summary)
            first = highlighted[0]
            if isinstance(first, Text):
                lines.append(format_activity_primary('Finished', first))
            else:
                lines.append(format_activity_primary('Finished', 'Result:'))
                lines.append(first)
            lines.extend(highlighted[1:])
        else:
            lines.append(format_activity_primary('Finished', summary))

    stats_parts: list[str] = []
    if files_changed > 0:
        stats_parts.append(f'{files_changed} files')
    if lines_added > 0:
        stats_parts.append(f'[{CLR_STATUS_OK}]+{lines_added}[/{CLR_STATUS_OK}]')
    if lines_removed > 0:
        stats_parts.append(f'[{CLR_DETAIL}]-{lines_removed}[/{CLR_DETAIL}]')

    if stats_parts:
        lines.append('  ' + '  ·  '.join(stats_parts))

    meta_parts: list[str] = []
    if duration:
        meta_parts.append(duration)
    if tool_calls > 0:
        meta_parts.append(f'{tool_calls} calls')

    if meta_parts:
        lines.append(
            '  '
            + '  ·  '.join(
                f'[{CLR_SECONDARY}]{p}[/{CLR_SECONDARY}]' for p in meta_parts
            )
        )

    if files:
        lines.append('')
        for filepath in files[:8]:
            lines.append(f'  [{CLR_STATUS_OK}]·[/{CLR_STATUS_OK}]  {filepath}')
        if len(files) > 8:
            lines.append(f'  [dim]... {len(files) - 8} more[/dim]')

    return lines
