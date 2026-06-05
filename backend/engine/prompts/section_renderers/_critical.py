"""Renderer for the critical-execution partial (system_partial_04_critical.md)."""

from __future__ import annotations

from collections.abc import Callable


def _render_critical(
    render_partial: Callable[..., str],
    terminal_command_tool: str,
    *,
    terminal_manager_available: bool,
    tracker_on: bool,
    checkpoints_on: bool,
    meta_cognition_on: bool,
) -> str:
    """Render last-mile critical execution rules with dynamic terminal tool naming."""
    think_execution_rule = '**Reasoning alone does not execute** — after reasoning, you must still call tools.'
    if terminal_manager_available:
        terminal_manager_rule = (
            '**Interactive terminal state diagram**: `open` (spawns process and returns session id) -> `read` -> `input` -> `read`.\n'
            '**Rules**: 1) Reuse `session_id`, 2) Use `mode=delta` when reading, 3) Wait for output instead of repeating inputs.'
        )
    else:
        terminal_manager_rule = ''

    task_tracker_antipattern = (
        '- **Calling `finish` with `task_tracker` items still `todo` or `in_progress`.** Sync the tracker first.'
        if tracker_on
        else ''
    )

    destructive_ops_antipattern = (
        '- **Running `rm`, `Remove-Item`, force pushes, or other destructive ops without explicit confirmation from the confirmation gate.**'
        + (' If available, take a `checkpoint` first.' if checkpoints_on else '')
    )

    planning_tool_list = (
        '`create_task_tracker`, `task_tracker`, `{terminal_command_tool}`, and the public file API tools'
        if tracker_on
        else '`{terminal_command_tool}` and the public file API tools'
    )

    user_question_antipattern = (
        '**Asking the user a question in plain prose mid-turn** when `communicate_with_user` is available. The turn must end so the user can answer.'
        if meta_cognition_on
        else '**Asking the user a question in plain prose mid-turn** when a blocking clarification is needed. If you must ask, ask the user a short clarifying question in natural language and wait for the answer instead of continuing with guesses.'
    )
    return render_partial(
        'system_partial_04_critical.md',
        terminal_command_tool=terminal_command_tool,
        terminal_manager_rule=terminal_manager_rule,
        think_execution_rule=think_execution_rule,
        task_tracker_antipattern=task_tracker_antipattern,
        destructive_ops_antipattern=destructive_ops_antipattern,
        planning_tool_list=planning_tool_list,
        user_question_antipattern=user_question_antipattern,
    )
