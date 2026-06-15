"""Delegation renderer showing worker task status."""

from __future__ import annotations

from typing import Any

from backend.cli.display.transcript import format_activity_primary
from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_SECONDARY,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
)


def _count_by_status(tasks: list[dict[str, str]], status: str) -> int:
    return sum(1 for t in tasks if t.get('status') == status)


def _count_worker_statuses(tasks: list[dict[str, str]]) -> tuple[int, int, int]:
    return (
        _count_by_status(tasks, 'running'),
        _count_by_status(tasks, 'done'),
        _count_by_status(tasks, 'failed'),
    )


def _build_status_line(running: int, done: int, failed: int) -> str | None:
    parts = []
    if running:
        parts.append(f'[{CLR_BRAND_HUE}]{running} running[/]')
    if done:
        parts.append(f'[{CLR_STATUS_OK}]{done} done[/]')
    if failed:
        parts.append(f'[{CLR_STATUS_ERR}]{failed} failed[/]')
    return '  ·  '.join(parts) if parts else None


def _render_worker_task(task: dict[str, str], index: int) -> str:
    name = task.get('name', task.get('description', f'Task {index}'))
    status = task.get('status', 'unknown')
    if status == 'running':
        dot = f'[{CLR_BRAND_HUE}]●[/{CLR_BRAND_HUE}]'
    elif status == 'done':
        dot = f'[{CLR_STATUS_OK}]✓[/{CLR_STATUS_OK}]'
    elif status == 'failed':
        dot = f'[{CLR_STATUS_ERR}]✗[/{CLR_STATUS_ERR}]'
    else:
        dot = f'[{CLR_SECONDARY}]○[/{CLR_SECONDARY}]'
    return f'  {dot}  [dim]{name}[/dim]'


def render_delegation(
    total_workers: int,
    tasks: list[dict[str, str]] | None = None,
) -> list[Any]:
    """Render delegation status with worker tasks."""
    lines: list[Any] = []
    lines.append(format_activity_primary('Delegated', f'{total_workers} tasks'))
    if not tasks:
        return lines
    lines.append('')
    running, done, failed = _count_worker_statuses(tasks)
    status_line = _build_status_line(running, done, failed)
    if status_line:
        lines.append('  ' + status_line)
        lines.append('')
    for i, task in enumerate(tasks[:5], 1):
        lines.append(_render_worker_task(task, i))
    if len(tasks) > 5:
        lines.append(f'  [dim]... {len(tasks) - 5} more[/dim]')
    return lines
