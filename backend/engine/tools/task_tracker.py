"""Structured task tracking tool definition for Orchestrator runs."""

from typing import Any

from backend.core.tasks.task_status import (
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_SKIPPED,
    TASK_STATUS_TODO,
)
from backend.core.tasks.task_tracker import TaskTracker
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition, get_command_param
from backend.core.tools.tool_names import TASK_TRACKER_TOOL_NAME

_TASK_TRACKER_DESCRIPTION = (
    'Maintain a structured plan to track progress. '
    'Use `update` with a task_list to create or overwrite the plan. '
    'Use `view` (without a task_list) to read the current plan. '
    'Use `update_status` to change a single task status by ID (no need to re-emit full list). '
    'Statuses must be exactly one of: `todo`, `in_progress`, `done`, `skipped`, `blocked`. '
    'Terminal states before completion are `done`, `skipped`, `blocked`.'
)

_TASK_STATUS_DESCRIPTION = (
    'Current status. Must be exactly one of: todo, in_progress, done, skipped, blocked.'
)


def _task_step_schema(depth: int = 2) -> dict[str, Any]:
    """Return the task-list item schema, including bounded nested subtasks."""
    properties: dict[str, Any] = {
        'id': {
            'type': 'string',
            'description': "Unique identifier (e.g. '1', '1.1').",
        },
        'description': {
            'type': 'string',
            'description': 'Concise description of the step.',
        },
        'status': {
            'type': 'string',
            'description': _TASK_STATUS_DESCRIPTION,
            'enum': [
                TASK_STATUS_TODO,
                TASK_STATUS_IN_PROGRESS,
                TASK_STATUS_DONE,
                TASK_STATUS_SKIPPED,
                TASK_STATUS_BLOCKED,
            ],
        },
        'result': {
            'type': 'string',
            'description': 'Optional result or note captured for this step.',
        },
        'tags': {
            'type': 'array',
            'description': 'Optional tags for this step.',
            'items': {'type': 'string'},
        },
    }
    properties['subtasks'] = {
        'type': 'array',
        'description': 'Optional child steps following the same task item shape.',
        'items': _task_step_schema(depth - 1) if depth > 0 else {'type': 'object'},
    }
    return {
        'type': 'object',
        'properties': properties,
        'required': ['id', 'description', 'status'],
        'additionalProperties': False,
    }


def create_task_tracker_tool() -> ChatCompletionToolParam:
    """Create the task tracker tool for the Orchestrator agent."""
    return create_tool_definition(
        name=TASK_TRACKER_TOOL_NAME,
        description=_TASK_TRACKER_DESCRIPTION,
        properties={
            'command': get_command_param(
                'The command to execute. `view` shows the current plan. `update` overwrites the entire plan with the new list. `update_status` changes a single task status by ID.',
                ['view', 'update', 'update_status'],
            ),
            'task_list': {
                'type': 'array',
                'description': 'The complete ordered list of plan steps. Must include ALL steps - not just the update. Required for `update`.',
                'items': _task_step_schema(),
            },
            'title': {
                'type': 'string',
                'description': 'Title for the current plan.',
            },
            'task_id': {
                'type': 'string',
                'description': "For 'update_status': the ID of the task to update (e.g. '1', '1.1', '2').",
            },
            'status': {
                'type': 'string',
                'description': f"For 'update_status': new status value. {_TASK_STATUS_DESCRIPTION}",
                'enum': [
                    TASK_STATUS_TODO,
                    TASK_STATUS_IN_PROGRESS,
                    TASK_STATUS_DONE,
                    TASK_STATUS_SKIPPED,
                    TASK_STATUS_BLOCKED,
                ],
            },
            'result': {
                'type': 'string',
                'description': "For 'update_status': optional outcome or note about the task (e.g. 'Fixed auth bug - missing token refresh').",
            },
        },
        required=['command'],
    )


__all__ = ['TaskTracker', 'create_task_tracker_tool']
