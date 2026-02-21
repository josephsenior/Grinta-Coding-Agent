"""delegate_task tool — spawn sub-agents for parallelizable tasks.

Allows the orchestrator to map-reduce its workload by spinning up isolated
workers with constrained tools to solve parallelizable sub-problems.
"""

from __future__ import annotations

from backend.events.action.agent import DelegateTaskAction

DELEGATE_TASK_TOOL_NAME = "delegate_task"


def create_delegate_task_tool() -> dict:
    """Return the OpenAI function-calling tool definition for delegate_task."""
    return {
        "type": "function",
        "function": {
            "name": DELEGATE_TASK_TOOL_NAME,
            "description": (
                "Delegate a specific, isolated sub-task to a worker agent. "
                "Use this to parallelize work such as writing unit tests for "
                "multiple files, summarizing text, or performing isolated refactors. "
                "The worker agent will have its own runtime and context, "
                "and will return its final observation once complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "Clear and detailed instructions for the worker agent about what to accomplish.",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths the worker agent needs to read or modify.",
                    },
                },
                "required": ["task_description", "files"],
            },
        },
    }


def build_delegate_task_action(arguments: dict) -> DelegateTaskAction:
    """Build the action for the delegate_task tool call."""
    from backend.core.exceptions import FunctionCallValidationError

    if "task_description" not in arguments:
        raise FunctionCallValidationError(
            'Missing required argument "task_description" in tool call delegate_task'
        )
    if "files" not in arguments:
        raise FunctionCallValidationError(
            'Missing required argument "files" in tool call delegate_task'
        )

    task_description = arguments["task_description"]
    files = arguments.get("files", [])

    if not isinstance(files, list):
        files = [files]

    return DelegateTaskAction(
        task_description=task_description,
        files=files,
    )
