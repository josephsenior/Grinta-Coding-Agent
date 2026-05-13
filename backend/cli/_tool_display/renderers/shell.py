"""Shell command renderer.

Badge + command label + first lines of output, uniform for all commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    CLR_SECONDARY,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
)
from backend.cli.transcript import format_activity_primary

if TYPE_CHECKING:
    from rich.console import Console


def render_shell_command(
    command: str,
    output: str | None = None,
    exit_code: int | None = None,
    duration: str = '',
    *,
    console: "Console | None" = None,
) -> list[str]:
    """Render a shell command with badge + command + output preview.

    Returns a list of lines suitable for console.print().
    """
    lines: list[str] = []
    badge = badge_for_tool_name('execute_bash')

    cmd_display = command.strip()
    if len(cmd_display) > 80:
        cmd_display = cmd_display[:77] + '…'
    cmd_label = f"$ [dim]{cmd_display}[/dim]"

    lines.append(badge.render())
    lines.append(format_activity_primary('Ran', cmd_label))

    if duration:
        lines.append(f"  [dim]{duration}[/dim]")

    if exit_code is not None:
        if exit_code == 0:
            lines.append(f"  [{CLR_STATUS_OK}]✓ exit 0[/]")
        else:
            lines.append(f"  [{CLR_STATUS_ERR}]✗ exit {exit_code}[/]")

    if output:
        raw_lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
        preview = raw_lines[:8]
        for line in preview:
            if len(line) > 120:
                line = line[:117] + '…'
            lines.append(f"  {line}")
        if len(raw_lines) > 8:
            lines.append(f"  [dim]... {len(raw_lines) - 8} more lines[/dim]")

    return lines