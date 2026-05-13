"""Delegation renderer showing worker task status."""

from __future__ import annotations

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    CLR_STATUS_ERR,
    CLR_SECONDARY,
    CLR_BRAND_HUE,
)
from backend.cli.transcript import format_activity_primary


def render_delegation(
    total_workers: int,
    tasks: list[dict[str, str]] | None = None,
) -> list[str]:
    """Render delegation status with worker tasks."""
    lines: list[str] = []

    lines.append(format_activity_primary('Delegated', f'{total_workers} tasks'))

    if not tasks:
        return lines

    lines.append('')

    running = sum(1 for t in tasks if t.get('status') == 'running')
    done = sum(1 for t in tasks if t.get('status') == 'done')
    failed = sum(1 for t in tasks if t.get('status') == 'failed')

    status_parts = []
    if running:
        status_parts.append(f"[{CLR_BRAND_HUE}]{running} running[/]")
    if done:
        status_parts.append(f"[{CLR_STATUS_OK}]{done} done[/]")
    if failed:
        status_parts.append(f"[{CLR_STATUS_ERR}]{failed} failed[/]")

    if status_parts:
        lines.append('  ' + '  ·  '.join(status_parts))
        lines.append('')

    for i, task in enumerate(tasks[:5], 1):
        name = task.get('name', task.get('description', f'Task {i}'))
        status = task.get('status', 'unknown')

        if status == 'running':
            dot = f"[{CLR_BRAND_HUE}]●[/{CLR_BRAND_HUE}]"
            lines.append(f"  {dot}  [dim]{name}[/dim]")
        elif status == 'done':
            dot = f"[{CLR_STATUS_OK}]✓[/{CLR_STATUS_OK}]"
            lines.append(f"  {dot}  [dim]{name}[/dim]")
        elif status == 'failed':
            dot = f"[{CLR_STATUS_ERR}]✗[/{CLR_STATUS_ERR}]"
            lines.append(f"  {dot}  [dim]{name}[/dim]")
        else:
            dot = f"[{CLR_SECONDARY}]○[/{CLR_SECONDARY}]"
            lines.append(f"  {dot}  [dim]{name}[/dim]")

    if len(tasks) > 5:
        lines.append(f"  [dim]... {len(tasks) - 5} more[/dim]")

    return lines