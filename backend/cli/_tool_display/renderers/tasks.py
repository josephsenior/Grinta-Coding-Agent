"""Task tracker renderer with task list display."""

from __future__ import annotations

from typing import Any

from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_DETAIL,
    CLR_SECONDARY,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
)
from backend.cli.transcript import format_activity_primary


def render_task_list(
    tasks: list[dict[str, str]],
    title: str = 'Tasks',
) -> list[Any]:
    """Render a task list with status indicators."""
    lines: list[Any] = []

    active = sum(
        1 for t in tasks if t.get('status') in ('active', 'in_progress', 'running')
    )
    done = sum(1 for t in tasks if t.get('status') in ('done', 'completed', 'finished'))
    blocked = sum(1 for t in tasks if t.get('status') in ('blocked', 'waiting'))

    status_parts = []
    if active:
        status_parts.append(f'[{CLR_BRAND_HUE}]{active} active[/]')
    if done:
        status_parts.append(f'[{CLR_STATUS_OK}]{done} done[/]')
    if blocked:
        status_parts.append(f'[{CLR_STATUS_ERR}]{blocked} blocked[/]')

    status_str = '  '.join(status_parts) if status_parts else f'{len(tasks)} tasks'

    lines.append(format_activity_primary('Tracked', status_str))

    lines.append('')

    for task in tasks[:8]:
        name = task.get(
            'description', task.get('name', task.get('title', 'Unknown task'))
        )
        status = task.get('status', 'pending')
        progress = task.get('progress', task.get('pct', ''))

        if status in ('done', 'completed', 'finished'):
            dot = f'[{CLR_STATUS_OK}]✓[/{CLR_STATUS_OK}]'
            name_style = CLR_SECONDARY
        elif status in ('blocked', 'waiting'):
            dot = f'[{CLR_STATUS_ERR}]□[/{CLR_STATUS_ERR}]'
            name_style = CLR_STATUS_ERR
        elif status in ('active', 'in_progress', 'running'):
            dot = f'[{CLR_BRAND_HUE}]●[/{CLR_BRAND_HUE}]'
            name_style = CLR_DETAIL
        else:
            dot = f'[{CLR_SECONDARY}]○[/{CLR_SECONDARY}]'
            name_style = CLR_SECONDARY

        progress_str = f'  [dim]{progress}[/dim]' if progress else ''

        name_display = name
        if len(name_display) > 60:
            name_display = name_display[:57] + '…'

        lines.append(
            f'  {dot}  [{name_style}]{name_display}[/{name_style}]{progress_str}'
        )

    if len(tasks) > 8:
        lines.append(f'  [dim]... {len(tasks) - 8} more tasks[/dim]')

    return lines


def render_task_summary(
    active: int = 0,
    completed: int = 0,
    blocked: int = 0,
) -> list[Any]:
    """Render just the task summary line."""
    parts = []
    if active:
        parts.append(f'[{CLR_BRAND_HUE}]{active} active[/]')
    if completed:
        parts.append(f'[{CLR_STATUS_OK}]{completed} done[/]')
    if blocked:
        parts.append(f'[{CLR_STATUS_ERR}]{blocked} blocked[/]')

    if parts:
        return [format_activity_primary('Tracked', '  '.join(parts))]
    return [format_activity_primary('Tracked', f'{active + completed + blocked} tasks')]
