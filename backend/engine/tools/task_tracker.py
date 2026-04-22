"""Structured task tracking tool definition for Orchestrator runs."""

import json
from pathlib import Path
from typing import Any

from backend.core.task_status import (
    TASK_STATUS_DOING,
    TASK_STATUS_DONE,
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
    'Use only these statuses: `todo`, `doing`, and `done`.'
)


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

        from backend.orchestration.state.state import normalize_plan_step_payload

        try:
            return [
                normalize_plan_step_payload(task, i + 1) for i, task in enumerate(data)
            ]
        except TypeError:
            return []

    def save_to_file(self, task_list: list[dict[str, Any]]) -> None:
        """Save the task list to disk."""
        from backend.orchestration.state.state import normalize_plan_step_payload

        normalized = [
            normalize_plan_step_payload(task, i + 1) for i, task in enumerate(task_list)
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)


def create_task_tracker_tool() -> ChatCompletionToolParam:
    """Create the task tracker tool for the Orchestrator agent."""
    return create_tool_definition(
        name=TASK_TRACKER_TOOL_NAME,
        description=_TASK_TRACKER_DESCRIPTION,
        properties={
            'command': get_command_param(
                'The command to execute. `view` shows the current plan. `update` overwrites the entire plan with the new list.',
                ['view', 'update'],
            ),
            'task_list': {
                'type': 'array',
                'description': 'The complete ordered list of plan steps. Must include ALL steps - not just the update. Required for `update`.',
                'items': {
                    'type': 'object',
                    'properties': {
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
                            'description': 'Current status. Allowed values: todo | doing | done.',
                            'enum': [
                                TASK_STATUS_TODO,
                                TASK_STATUS_DOING,
                                TASK_STATUS_DONE,
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
                        'subtasks': {
                            'type': 'array',
                            'description': 'Optional child steps following the same task item shape.',
                            'items': {'type': 'object'},
                        },
                    },
                    'required': ['id', 'description', 'status'],
                    'additionalProperties': False,
                },
            },
            'title': {
                'type': 'string',
                'description': 'Title for the current plan.',
            },
        },
        required=['command'],
    )
