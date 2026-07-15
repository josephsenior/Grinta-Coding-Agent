"""Renderer for the worked-examples partial (system_partial_05_examples.md)."""

from __future__ import annotations

from collections.abc import Callable

from backend.core.tools.tool_names import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    GLOB_TOOL_NAME,
    GREP_TOOL_NAME,
    LSP_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_FILE_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
)


def _tool_ref(name: str) -> str:
    return f'`{name}`'


def _build_search_tools(*, lsp_available: bool) -> str:
    parts = [
        _tool_ref(GREP_TOOL_NAME),
        _tool_ref(GLOB_TOOL_NAME),
        _tool_ref(FIND_SYMBOLS_TOOL_NAME),
    ]
    if lsp_available:
        parts.append(_tool_ref(LSP_TOOL_NAME))
    return '/'.join(parts)


def _build_structured_work_prefix(*, criteria_on: bool, tracker_on: bool) -> str:
    _ = criteria_on
    return 'See <TASK_STATE> → ' if tracker_on else ''


def _build_bug_fix_pattern(
    *,
    criteria_on: bool,
    tracker_on: bool,
) -> str:
    prefix = _build_structured_work_prefix(
        criteria_on=criteria_on, tracker_on=tracker_on
    )
    if tracker_on:
        return (
            prefix + 'task_state(set for substantial work) → discover → edit → '
            'verify → task_state(update/audit/review) → decide whether the overall '
            'objective is complete or blocked → final summary.'
        )
    return 'Discover → edit → verify → final summary.'


def _build_feature_pattern(
    *,
    criteria_on: bool,
    tracker_on: bool,
) -> str:
    prefix = _build_structured_work_prefix(
        criteria_on=criteria_on, tracker_on=tracker_on
    )
    if tracker_on:
        return (
            prefix + 'task_state(set for substantial work) → analyze → edit → '
            'test/lint → task_state(update/audit/review) → decide whether the '
            'overall objective is complete or blocked → final summary.'
        )
    return 'Scope → analyze → edit → test/lint → final summary.'


def _render_examples(
    render_partial: Callable[..., str],
    *,
    terminal_command_tool: str,
    tracker_on: bool,
    criteria_on: bool = True,
    working_memory_on: bool,
    lsp_available: bool,
    checkpoints_on: bool,
    web_on: bool = True,
) -> str:
    """Render the worked-examples partial with capability-aware tool references."""
    _ = (working_memory_on, web_on, terminal_command_tool)
    search_tools = _build_search_tools(lsp_available=lsp_available)

    destructive_confirmation_step = 'See `<ASK_USER_TOOL>` to confirm scope and target'
    if checkpoints_on:
        checkpoint_step = 'After the change, verify immediately; if it fails, `checkpoint(revert)` or `undo_last_edit`'
    else:
        checkpoint_step = 'If approved, keep the change surface small and verify immediately after the action'
    adjacent_tool_fallback = (
        f'symbol lookup → {_tool_ref(GREP_TOOL_NAME)}; '
        f'{_tool_ref(LSP_TOOL_NAME)} → {_tool_ref(GREP_TOOL_NAME)}'
        if lsp_available
        else f'symbol lookup → {_tool_ref(GREP_TOOL_NAME)}; refine the query and read nearby files'
    )
    failure_escalation_step = (
        'After repeated failed attempts on the same sub-task, see `<ASK_USER_TOOL>` '
        'with a 1-line post-mortem and a specific question'
    )

    bug_fix_pattern = _build_bug_fix_pattern(
        criteria_on=criteria_on, tracker_on=tracker_on
    )
    feature_pattern = _build_feature_pattern(
        criteria_on=criteria_on, tracker_on=tracker_on
    )

    return render_partial(
        'system_partial_05_examples.md',
        search_tools=search_tools,
        read_tool=_tool_ref(READ_FILE_TOOL_NAME),
        analyze_tool=_tool_ref(ANALYZE_PROJECT_STRUCTURE_TOOL_NAME),
        multiedit_tool=_tool_ref(MULTIEDIT_TOOL_NAME),
        replace_string_tool=_tool_ref(REPLACE_STRING_TOOL_NAME),
        bug_fix_pattern=bug_fix_pattern,
        feature_pattern=feature_pattern,
        destructive_confirmation_step=destructive_confirmation_step,
        checkpoint_step=checkpoint_step,
        adjacent_tool_fallback=adjacent_tool_fallback,
        failure_escalation_step=failure_escalation_step,
    )
