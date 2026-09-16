"""delegate_task tool — spawn read-only worker agents for parallel investigation.

Lets the orchestrator fan out research it would otherwise run in its own
context, then reduce the workers' conclusions. Workers are read-only: the
file-editing tools are withheld from them and their workspace is mounted
read-only, so a worker can report what should change but never changes it.
"""

from __future__ import annotations

from backend.core.constants import (
    DELEGATE_WORKER_TIMEOUT_SECONDS,
    MAX_PARALLEL_DELEGATE_WORKERS,
)
from backend.core.tools.tool_names import DELEGATE_TASK_TOOL_NAME
from backend.ledger.action.agent import DelegateTaskAction


def create_delegate_task_tool() -> dict:
    """Return the OpenAI function-calling tool definition for delegate_task."""
    return {
        'type': 'function',
        'function': {
            'name': DELEGATE_TASK_TOOL_NAME,
            'description': (
                'Delegate a read-only investigation to a worker agent. Use this to '
                'parallelize research across a large codebase — tracing how a feature '
                'works, finding every call site of a symbol, summarizing a subsystem — '
                'and get back a conclusion instead of spending your own context on the '
                'search.\n\n'
                'The worker has its own context and returns its final observation when '
                'done. It can read, search and run read commands freely, but it CANNOT '
                'modify the workspace: the file-editing tools are withheld from it and '
                'its filesystem is mounted read-only. Apply any change it recommends '
                'yourself.\n\n'
                'PARALLEL MODE: pass `parallel_tasks` (a list of objects, each with '
                "'task_description') instead of `task_description` to run several "
                f'investigations at once, up to {MAX_PARALLEL_DELEGATE_WORKERS}. The '
                'observation contains every worker result.\n\n'
                'LIMITS:\n'
                '- Workers cannot delegate further; delegation is one level deep.\n'
                f'- A worker is terminated after {int(DELEGATE_WORKER_TIMEOUT_SECONDS)}s.\n'
                '- You wait for the result, so delegate only work you need before '
                'continuing.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'task_description': {
                        'type': 'string',
                        'description': (
                            'Clear and detailed instructions for a single worker, '
                            'including what it should report back. Required unless '
                            'parallel_tasks is provided.'
                        ),
                    },
                    'files': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': (
                            'File paths the worker should start from. Advisory only — '
                            'the worker can read anything in the workspace.'
                        ),
                    },
                    'parallel_tasks': {
                        'type': 'array',
                        'description': (
                            'Independent investigations to run concurrently. '
                            'When provided, task_description and files at the top '
                            'level are ignored. At most '
                            f'{MAX_PARALLEL_DELEGATE_WORKERS} are accepted.'
                        ),
                        'items': {
                            'type': 'object',
                            'properties': {
                                'task_description': {
                                    'type': 'string',
                                    'description': 'What this specific worker should investigate.',
                                },
                                'files': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Files relevant to this sub-task.',
                                },
                            },
                            'required': ['task_description'],
                        },
                    },
                },
            },
        },
    }


def build_delegate_task_action(arguments: dict, depth: int = 0) -> DelegateTaskAction:
    """Build the action for the delegate_task tool call.

    Args:
        arguments: Tool call arguments from the LLM.
        depth: Current delegation depth (0 = parent, 1 = first-level worker, etc.).
            Used to prevent infinite recursion.
    """
    from backend.core.errors import FunctionCallValidationError

    parallel_tasks = arguments.get('parallel_tasks', [])
    # Background workers are not exposed in the schema: there is no join or
    # handle for them yet, so a background result would be unobservable. The
    # handler still supports the flag for programmatic callers.
    run_in_background = arguments.get('run_in_background', False)
    if parallel_tasks:
        if len(parallel_tasks) > MAX_PARALLEL_DELEGATE_WORKERS:
            raise FunctionCallValidationError(
                f'parallel_tasks has {len(parallel_tasks)} entries, which exceeds the '
                f'limit of {MAX_PARALLEL_DELEGATE_WORKERS} concurrent workers. '
                'Group the work into fewer, broader investigations.'
            )
        # Parallel mode — validate each task has task_description
        for i, t in enumerate(parallel_tasks):
            if not t.get('task_description'):
                raise FunctionCallValidationError(
                    f"parallel_tasks[{i}] is missing required 'task_description'"
                )
        return DelegateTaskAction(
            parallel_tasks=parallel_tasks,
            run_in_background=run_in_background,
            depth=depth,
        )

    # Single task mode — files is optional (the worker can discover them).
    if 'task_description' not in arguments:
        raise FunctionCallValidationError(
            'Missing required argument "task_description" in tool call delegate_task'
        )

    task_description = arguments['task_description']
    files = arguments.get('files', [])

    if not isinstance(files, list):
        files = [files]

    return DelegateTaskAction(
        task_description=task_description,
        files=files,
        run_in_background=run_in_background,
        depth=depth,
    )
