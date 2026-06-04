"""Structured task tracking tool definition for Orchestrator runs."""

import json
from pathlib import Path
from typing import Any

from backend.core.task_status import (
    TASK_STATUS_BLOCKED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_DONE,
    TASK_STATUS_SKIPPED,
    TASK_STATUS_TODO,
)
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
)
from backend.inference.tool_names import TASK_TRACKER_TOOL_NAME

_TASK_TRACKER_DESCRIPTION = (
    'Maintain a structured plan to track progress. '
    'Use `update` with a task_list to create or overwrite the plan. '
    'Use `view` (without a task_list) to read the current plan. '
    'Use `update_status` to change a single task status by ID (no need to re-emit full list). '
    'Statuses must be exactly one of: `todo`, `in_progress`, `done`, `skipped`, `blocked`. '
    'Terminal states for finish are `done`, `skipped`, `blocked`.'
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


class TaskTracker:
    """Manages the persistence of the task plan to disk."""

    def __init__(self, workspace_root: str | Path | None = None):
        """Initialize the task tracker with a workspace root."""
        if workspace_root is None:
            from backend.core.workspace_resolution import (
                require_effective_workspace_root,
            )

            workspace_root = require_effective_workspace_root()
        from backend.core.workspace_resolution import workspace_agent_state_dir

        self.path = workspace_agent_state_dir(workspace_root) / 'active_plan.json'

    def load_from_file(self) -> list[dict[str, Any]]:
        """Load the task list from disk."""
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        if not isinstance(data, list):
            return []

        from backend.core.contracts.state import normalize_plan_step_payload

        try:
            return [
                normalize_plan_step_payload(task, i + 1) for i, task in enumerate(data)
            ]
        except TypeError:
            return []

    def save_to_file(self, task_list: list[dict[str, Any]]) -> None:
        """Save the task list to disk."""
        from backend.core.contracts.state import normalize_plan_step_payload

        normalized = [
            normalize_plan_step_payload(task, i + 1) for i, task in enumerate(task_list)
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)

    def update_task_status(
        self, task_id: str, status: str, result: str | None = None
    ) -> tuple[bool, str]:
        """Update status of a single task by ID.

        Args:
            task_id: The ID of the task to update (e.g., '1', '1.1', '2')
            status: New status value
            result: Optional result or note about the task outcome

        Returns:
            Tuple of (success, message)
        """
        valid_statuses = {
            TASK_STATUS_TODO,
            TASK_STATUS_IN_PROGRESS,
            TASK_STATUS_DONE,
            TASK_STATUS_SKIPPED,
            TASK_STATUS_BLOCKED,
        }
        if status not in valid_statuses:
            return (
                False,
                f"Invalid status '{status}'. Valid: {', '.join(sorted(valid_statuses))}",
            )

        task_list = self.load_from_file()
        if not task_list:
            return False, 'No tasks found. Create a plan first with update command.'

        task = _find_task_by_id(task_list, task_id)
        if task is None:
            return False, f"Task '{task_id}' not found."

        old_status = task.get('status', 'unknown')
        task['status'] = status
        if result is not None:
            task['result'] = result
        self.save_to_file(task_list)
        return True, f"Task '{task_id}' status updated: {old_status} -> {status}"


def _find_task_by_id(
    task_list: list[dict[str, Any]], task_id: str
) -> dict[str, Any] | None:
    """Find a task by ID in the task list, including nested subtasks."""
    for task in task_list:
        if task.get('id') == task_id:
            return task
        # Search subtasks recursively
        subtasks = task.get('subtasks', [])
        if subtasks:
            found = _find_task_by_id(subtasks, task_id)
            if found is not None:
                return found
    return None


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
