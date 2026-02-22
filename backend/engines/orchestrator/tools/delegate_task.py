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
                "and will return its final observation once complete.\n\n"
                "PARALLEL MODE: Pass `parallel_tasks` (a list of task objects) instead of "
                "`task_description` to spawn all workers simultaneously and wait for all "
                "to finish. Each task object needs 'task_description' and optionally 'files'. "
                "Use parallel mode when sub-tasks are fully independent (no shared files)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "Clear and detailed instructions for a single worker agent. Required unless parallel_tasks is provided.",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths the worker agent needs to read or modify.",
                    },
                    "parallel_tasks": {
                        "type": "array",
                        "description": (
                            "List of independent sub-tasks to run concurrently. "
                            "When provided, task_description and files at the top level are ignored. "
                            "All workers run in parallel; the observation contains all their results."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "task_description": {
                                    "type": "string",
                                    "description": "What this specific worker should do.",
                                },
                                "files": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Files relevant to this sub-task.",
                                },
                            },
                            "required": ["task_description"],
                        },
                    },
                },
            },
        },
    }


def build_delegate_task_action(arguments: dict) -> DelegateTaskAction:
    """Build the action for the delegate_task tool call."""
    from backend.core.exceptions import FunctionCallValidationError

    parallel_tasks = arguments.get("parallel_tasks", [])
    if parallel_tasks:
        # Parallel mode — validate each task has task_description
        for i, t in enumerate(parallel_tasks):
            if not t.get("task_description"):
                raise FunctionCallValidationError(
                    f"parallel_tasks[{i}] is missing required 'task_description'"
                )
        return DelegateTaskAction(parallel_tasks=parallel_tasks)

    # Single task mode
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
