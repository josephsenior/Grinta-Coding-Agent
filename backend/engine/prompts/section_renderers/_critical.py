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
            '5. **Interactive sessions use `terminal_manager`** — call `open` once per session, '
            'then use `read`/`input` with the same `session_id`; do not call `open` again for follow-up commands.\n'
        )
    else:
        terminal_manager_rule = ''

    task_tracker_antipattern = (
        '- **Writing the final summary with `task_tracker` items still `todo` or `in_progress`.** Sync the tracker first.'
        if tracker_on
        else ''
    )

    destructive_ops_antipattern = '- **Running `rm`, `Remove-Item`, force pushes, or other destructive ops without explicit confirmation from the user.**'
    _ = checkpoints_on

    planning_tool_list = (
        f'`task_tracker`, `{terminal_command_tool}`, and the public file API tools'
        if tracker_on
        else f'`{terminal_command_tool}` and the public file API tools'
    )

    user_question_antipattern = (
        '**Asking the user a question in plain prose mid-turn.** See `<ASK_USER_TOOL>`.'
    )
    done_criteria_block = (
        '   **Done criteria by task type:**\n'
        '   - **Bugfix:** reproduce or capture the failing test, fix, then re-run the narrowest test/reproducer.\n'
        '   - **Implementation:** run lint/typecheck when the project uses them; smoke-test the changed path.\n'
        '   - **Refactor:** run affected tests or a narrow smoke check on touched modules.\n'
        '   - **Blocked verification:** state the concrete blocker (no harness, missing dependency/credential, '
        'environment cannot install/build/run, unsafe/destructive check, or no meaningful runnable check) before the final summary.'
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
        done_criteria_block=done_criteria_block,
    )
