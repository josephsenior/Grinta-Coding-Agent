"""Structured task tracking tool definition for CodeAct runs."""

from backend.engines.orchestrator.tools.common import (
    create_tool_definition,
    get_command_param,
)
from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.llm.tool_names import TASK_TRACKER_TOOL_NAME

_TASK_TRACKER_DESCRIPTION = (
    "Maintain a structured plan to track progress. "
    "Use `view` to see the current plan steps and `update` to overwrite the plan."
    "Always `view` if unsure, then `update` to keep the plan current."
)


def create_task_tracker_tool() -> ChatCompletionToolParam:
    """Create the task tracker tool for the CodeAct agent."""
    return create_tool_definition(
        name=TASK_TRACKER_TOOL_NAME,
        description=_TASK_TRACKER_DESCRIPTION,
        properties={
            "command": get_command_param(
                "The command to execute. `view` shows the current plan. `update` overwrites the entire plan with the new list.",
                ["view", "update"],
            ),
            "task_list": {
                "type": "array",
                "description": "The complete ordered list of plan steps. Must include ALL steps - not just the update. Required for `update`.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier (e.g. '1', '1.1').",
                        },
                        "description": {
                            "type": "string",
                            "description": "Concise description of the step.",
                        },
                        "status": {
                            "type": "string",
                            "description": "Current status.",
                            "enum": ["pending", "in_progress", "completed", "failed", "skipped"],
                        },
                        "result": {
                            "type": "string",
                            "description": "Result or output of the step.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["id", "description", "status"],
                    "additionalProperties": False,
                },
            },
            "title": {
                "type": "string",
                "description": "Title for the current plan.",
            },
        },
        required=["command"],
    )
