"""Renderer for the critical-execution partial (system_partial_04_critical.md)."""

from __future__ import annotations

from collections.abc import Callable


def _build_numbered_rules(rules: list[str]) -> str:
    """Number a list of rule strings starting from 1."""
    return '\n'.join(f'{i}. {r}' for i, r in enumerate(rules, 1))


def _build_agent_execution_block(
    terminal_command_tool: str,
    tracker_on: bool,
    think_execution_rule: str,
    terminal_manager_rule: str,
) -> tuple[str, str, str, str]:
    """Build execution block for agent mode (can_edit=True)."""
    edit_context_antipattern = '- **Editing existing content without current context.** Before mutating an existing file/symbol, inspect the relevant file, range, symbol, or anchor in this session. New file creation is exempt. New symbol creation requires reading the target file/anchor first. **Same bar for tests:** if you authored implementation earlier in the turn, **re-read it** before writing tests — memory drifts from the file on disk.\n'
    planning_tool_list = (
        f'`task_tracker`, `{terminal_command_tool}`, and the public file API tools'
        if tracker_on
        else f'`{terminal_command_tool}` and the public file API tools'
    )
    done_criteria_block = (
        '   **Done criteria by task type:**\n'
        '   - **Bugfix:** reproduce or capture the failing test, fix, then re-run the narrowest test/reproducer.\n'
        '   - **Implementation:** run lint/typecheck when the project uses them; smoke-test the changed path.\n'
        '   - **Refactor:** run affected tests or a narrow smoke check on touched modules.\n'
        '   - **Blocked verification:** state the concrete blocker (no harness, missing dependency/credential, '
        'environment cannot install/build/run, unsafe/destructive check, or no meaningful runnable check) before the final summary.'
    )
    rules: list[str] = [
        '**File changes require tool calls** — never claim "I created/edited" without an editor tool invocation.',
        f'To run commands, use `{terminal_command_tool}`; prose is not execution.',
        think_execution_rule,
        '**Never fabricate outcomes** — if a tool fails, report it honestly.',
    ]
    if terminal_manager_rule:
        rules.append(terminal_manager_rule)
    rules += [
        f'**Verify before final summary** — run the narrowest relevant proof: reproducer, tests, lint, or typecheck. If verification cannot run, state the concrete blocker: no test/build harness exists, missing dependency or credential, environment cannot install/build/run, verification would be unsafe/destructive, or the task has no meaningful runnable check. Do not use vague excuses like "not applicable."\n{done_criteria_block}',
        '**No unchanged retries after failure** — change strategy or escalate with hypothesis, action/outcome, and ruled-out paths.',
        '**Tests must track real APIs** — Before adding or changing test code, **read** the implementation module(s) you are testing in this session and align mocks, fixtures, and calls with the **actual** signatures and return shapes. Do not assume parity with a different module or an earlier draft from memory.',
        '**Postmortem on failing tests** — After a test failure, state the likely root cause class (wrong assumed API vs mock shape vs implementation bug vs flake), then change **one** lever and re-run a **narrow** test command; avoid blind rewrite loops.',
        '**Tests are executable evidence, not absolute truth.** When tests fail, diagnose whether the failure indicates an implementation bug, stale/incorrect test expectation, fixture/mock mismatch, environment issue, or flake. Fix implementation when tests expose a real defect. Update tests only when evidence shows they are stale, incorrect, or inconsistent with the requested behavior/current API. Never edit tests merely to manufacture a pass — including silently relaxing tolerances or skipping cases without an explained reason.',
        '**Non-test failures** — After tool/build/lint/runtime failure, state the **root-cause class** in one phrase (wrong path/symbol vs stale assumption vs environment vs defect); then follow `<ERROR_RECOVERY>` (pivot tools, never rerun the same failing command unchanged, escalate with hypothesis / action-outcome / ruled-out paths). (See "No unchanged retries after failure" above — that same rule applies here as well.)',
    ]
    numbered = _build_numbered_rules(rules)
    execution_rules_body = (
        '<CRITICAL_TOOL_EXECUTION_RULES>\n'
        'MANDATORY:\n\n'
        f'{numbered}\n'
        '</CRITICAL_TOOL_EXECUTION_RULES>'
    )
    return execution_rules_body, edit_context_antipattern, planning_tool_list, done_criteria_block


def _build_chat_plan_execution_block(
    tracker_on: bool,
    is_plan: bool,
) -> tuple[str, str, str, str]:
    """Build execution block for chat/plan mode (can_edit=False)."""
    edit_context_antipattern = ''
    planning_tool_list = ', '.join(
        filter(
            None,
            [
                '`task_tracker`' if tracker_on and is_plan else None,
                '`read_file`',
                '`read_symbols`',
                '`grep`',
                '`glob`',
                '`ask_user`',
            ],
        )
    )
    done_criteria_block = (
        '   **Done criteria:** state what you found or produced in plain text.'
    )
    chat_plan_rules = [
        '**Never fabricate outcomes** — if a tool fails, report it honestly.',
        '**No unchanged retries after failure** — change strategy or escalate with hypothesis, action/outcome, and ruled-out paths.',
        '**Non-tool responses end the turn** — plain text commits your response as final.',
    ]
    numbered = _build_numbered_rules(chat_plan_rules)
    execution_rules_body = (
        '<CRITICAL_TOOL_EXECUTION_RULES>\n'
        'MANDATORY:\n\n'
        f'{numbered}\n'
        '</CRITICAL_TOOL_EXECUTION_RULES>'
    )
    return execution_rules_body, edit_context_antipattern, planning_tool_list, done_criteria_block


def _render_critical(
    render_partial: Callable[..., str],
    terminal_command_tool: str,
    *,
    terminal_manager_available: bool,
    tracker_on: bool,
    checkpoints_on: bool,
    meta_cognition_on: bool,
    mode: str = 'agent',
) -> str:
    """Render last-mile critical execution rules with dynamic terminal tool naming."""
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
    )

    can_edit = not (is_chat_mode(mode) or is_plan_mode(mode))

    think_execution_rule = '**Reasoning alone does not execute** — after reasoning, you must still call tools.'
    terminal_manager_rule = (
        '**Shell vs interactive terminal** — use `{terminal_command_tool}` for one-shot commands '
        '(build, test, install, git). Use `terminal_manager` for interactive programs (REPLs, ssh, '
        '`python -i`, programs that ask questions) or reading detached background sessions.'
        if terminal_manager_available and can_edit
        else ''
    )

    task_tracker_antipattern = (
        '- **Writing the final summary with `task_tracker` items still `todo` or `in_progress`.** Sync the tracker first.'
        if tracker_on and can_edit
        else ''
    )
    destructive_ops_antipattern = (
        '- **Running `rm`, `Remove-Item`, force pushes, or other destructive ops without explicit confirmation from the user.**'
        if can_edit
        else ''
    )
    _ = checkpoints_on

    if can_edit:
        execution_rules_body, edit_context_antipattern, planning_tool_list, done_criteria_block = (
            _build_agent_execution_block(terminal_command_tool, tracker_on, think_execution_rule, terminal_manager_rule)
        )
    else:
        execution_rules_body, edit_context_antipattern, planning_tool_list, done_criteria_block = (
            _build_chat_plan_execution_block(tracker_on, is_plan_mode(mode))
        )

    user_question_antipattern = (
        '**Asking the user a question in plain prose mid-turn.** See `<ASK_USER_TOOL>`.'
    )

    return render_partial(
        'system_partial_04_critical.md',
        terminal_command_tool=terminal_command_tool,
        terminal_manager_rule=terminal_manager_rule,
        think_execution_rule=think_execution_rule,
        edit_context_antipattern=edit_context_antipattern,
        task_tracker_antipattern=task_tracker_antipattern,
        destructive_ops_antipattern=destructive_ops_antipattern,
        planning_tool_list=planning_tool_list,
        user_question_antipattern=user_question_antipattern,
        done_criteria_block=done_criteria_block,
        execution_rules_body=execution_rules_body,
    )
