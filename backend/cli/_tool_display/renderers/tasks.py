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


_ACTIVE_STATUSES = ('active', 'in_progress', 'running')
_DONE_STATUSES = ('done', 'completed', 'finished')
_BLOCKED_STATUSES = ('blocked', 'waiting')


def _count_matching(tasks: list[dict[str, str]], statuses: tuple[str, ...]) -> int:
    return sum(1 for t in tasks if t.get('status') in statuses)


def _count_statuses(tasks: list[dict[str, str]]) -> tuple[int, int, int]:
    return (
        _count_matching(tasks, _ACTIVE_STATUSES),
        _count_matching(tasks, _DONE_STATUSES),
        _count_matching(tasks, _BLOCKED_STATUSES),
    )


def _build_status_str(active: int, done: int, blocked: int, total: int) -> str:
    parts = []
    if active:
        parts.append(f'[{CLR_BRAND_HUE}]{active} active[/]')
    if done:
        parts.append(f'[{CLR_STATUS_OK}]{done} done[/]')
    if blocked:
        parts.append(f'[{CLR_STATUS_ERR}]{blocked} blocked[/]')
    return '  '.join(parts) if parts else f'{total} tasks'


def _task_dot_and_style(status: str) -> tuple[str, str]:
    if status in _DONE_STATUSES:
        return f'[{CLR_STATUS_OK}]✓[/{CLR_STATUS_OK}]', CLR_SECONDARY
    if status in _BLOCKED_STATUSES:
        return f'[{CLR_STATUS_ERR}]□[/{CLR_STATUS_ERR}]', CLR_STATUS_ERR
    if status in _ACTIVE_STATUSES:
        return f'[{CLR_BRAND_HUE}]●[/{CLR_BRAND_HUE}]', CLR_DETAIL
    return f'[{CLR_SECONDARY}]○[/{CLR_SECONDARY}]', CLR_SECONDARY


def _render_task_item(task: dict[str, str]) -> str:
    name = task.get(
        'description', task.get('name', task.get('title', 'Unknown task'))
    )
    status = task.get('status', 'pending')
    progress = task.get('progress', task.get('pct', ''))
    dot, name_style = _task_dot_and_style(status)
    progress_str = f'  [dim]{progress}[/dim]' if progress else ''
    if len(name) > 60:
        name = name[:57] + '…'
    return f'  {dot}  [{name_style}]{name}[/{name_style}]{progress_str}'


def render_task_list(
    tasks: list[dict[str, str]],
    title: str = 'Tasks',
) -> list[Any]:
    """Render a task list with status indicators."""
    lines: list[Any] = []
    active, done, blocked = _count_statuses(tasks)
    status_str = _build_status_str(active, done, blocked, len(tasks))
    lines.append(format_activity_primary('Tracked', status_str))
    lines.append('')
    for task in tasks[:8]:
        lines.append(_render_task_item(task))
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
