"""Structured task tracking tool definition for CodeAct runs."""

from backend.engines.orchestrator.tools.common import (
    create_tool_definition,
    get_command_param,
)
from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.llm.tool_names import TASK_TRACKER_TOOL_NAME

_TASK_TRACKER_DESCRIPTION = (
    "Maintain a structured list of tasks to track progress. "
    "Use `view` to see current tasks and `plan` to create or update the list. "
    "Always `view` the list before `plan`ing changes."
)


def create_task_tracker_tool() -> ChatCompletionToolParam:
    """Create the task tracker tool for the CodeAct agent."""
    return create_tool_definition(
        name=TASK_TRACKER_TOOL_NAME,
        description=_TASK_TRACKER_DESCRIPTION,
        properties={
            "command": get_command_param(
                "The command to execute. `view` shows the current task list. `plan` creates or updates the task list based on provided requirements and progress.",
                ["view", "plan"],
            ),
            "task_list": {
                "type": "array",
                "description": "The full task list. Required parameter of `plan` command.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique task identifier",
                        },
                        "title": {
                            "type": "string",
                            "description": "Brief task description",
                        },
                        "status": {
                            "type": "string",
                            "description": "Current task status",
                            "enum": ["todo", "in_progress", "done"],
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional additional context or details",
                        },
                    },
                    "required": ["title", "status", "id"],
                    "additionalProperties": False,
                },
            },
        },
        required=["command"],
    )
