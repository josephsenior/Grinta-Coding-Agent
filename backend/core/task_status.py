"""Canonical task tracker status vocabulary shared across the application."""

from __future__ import annotations

from typing import Any

TASK_STATUS_TODO = 'todo'
TASK_STATUS_DOING = 'doing'
TASK_STATUS_DONE = 'done'

TASK_STATUS_VALUES = frozenset(
    {TASK_STATUS_TODO, TASK_STATUS_DOING, TASK_STATUS_DONE}
)
ACTIVE_TASK_STATUSES = frozenset({TASK_STATUS_TODO, TASK_STATUS_DOING})
TERMINAL_TASK_STATUSES = frozenset({TASK_STATUS_DONE})

TASK_STATUS_PANEL_STYLES = {
    TASK_STATUS_TODO: 'cyan',
    TASK_STATUS_DOING: 'yellow',
    TASK_STATUS_DONE: 'green',
}

TASK_STATUS_PLAN_ICONS = {
    TASK_STATUS_TODO: '-',
    TASK_STATUS_DOING: 'O',
    TASK_STATUS_DONE: '✓',
}

TASK_STATUS_MARKDOWN_ICONS = {
    TASK_STATUS_TODO: '⏳',
    TASK_STATUS_DOING: '🔄',
    TASK_STATUS_DONE: '✅',
}


def normalize_task_status(
    raw_status: Any, *, default: str = TASK_STATUS_TODO
) -> str:
    """Return a canonical task status or raise for unsupported values."""
    if raw_status is None:
        return default

    status = str(raw_status).strip().lower()
    if not status:
        return default
    if status not in TASK_STATUS_VALUES:
        allowed = ', '.join(sorted(TASK_STATUS_VALUES))
        raise ValueError(
            f'Invalid task status {status!r}. Use one of: {allowed}.'
        )
    return status
