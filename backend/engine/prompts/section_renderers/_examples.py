"""Renderer for the worked-examples partial (system_partial_05_examples.md)."""

from __future__ import annotations

from collections.abc import Callable

from backend.core.tools.tool_names import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
    ASK_USER_TOOL_NAME,
    CODE_INTELLIGENCE_TOOL_NAME,
    CREATE_FILE_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    GLOB_TOOL_NAME,
    GREP_TOOL_NAME,
    MEMORY_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_FILE_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
    WEB_FETCH_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
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
        parts.append(_tool_ref(CODE_INTELLIGENCE_TOOL_NAME))
    return '/'.join(parts)


def _build_edit_tools() -> str:
    return (
        f'{_tool_ref(CREATE_FILE_TOOL_NAME)} / {_tool_ref(REPLACE_STRING_TOOL_NAME)} / '
        f'{_tool_ref(MULTIEDIT_TOOL_NAME)}'
    )


def _build_available_tools_summary(
    *,
    terminal_command_tool: str,
    lsp_available: bool,
    tracker_on: bool,
    working_memory_on: bool,
    web_on: bool,
) -> str:
    core = [
        GREP_TOOL_NAME,
        GLOB_TOOL_NAME,
        FIND_SYMBOLS_TOOL_NAME,
        READ_FILE_TOOL_NAME,
        ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
        CREATE_FILE_TOOL_NAME,
        REPLACE_STRING_TOOL_NAME,
        MULTIEDIT_TOOL_NAME,
        UNDO_LAST_EDIT_TOOL_NAME,
        terminal_command_tool,
        ASK_USER_TOOL_NAME,
    ]
    if web_on:
        core.extend([WEB_SEARCH_TOOL_NAME, WEB_FETCH_TOOL_NAME])
    if working_memory_on:
        core.append(MEMORY_TOOL_NAME)
    if lsp_available:
        core.append(CODE_INTELLIGENCE_TOOL_NAME)
    if tracker_on:
        core.append(TASK_TRACKER_TOOL_NAME)
    return ', '.join(_tool_ref(name) for name in core)


def _render_examples(
    render_partial: Callable[..., str],
    *,
    terminal_command_tool: str,
    tracker_on: bool,
    working_memory_on: bool,
    meta_cognition_on: bool,
    lsp_available: bool,
    checkpoints_on: bool,
    web_on: bool = True,
) -> str:
    """Render the worked-examples partial with capability-aware tool references."""
    _ = meta_cognition_on
    search_tools = _build_search_tools(lsp_available=lsp_available)
    edit_tools = _build_edit_tools()
    available_tools_summary = _build_available_tools_summary(
        terminal_command_tool=terminal_command_tool,
        lsp_available=lsp_available,
        tracker_on=tracker_on,
        working_memory_on=working_memory_on,
        web_on=web_on,
    )

    if tracker_on:
        planning_hint = f'{_tool_ref(TASK_TRACKER_TOOL_NAME)}(update) with a task_list when committing to structured work'
    else:
        planning_hint = 'scope the work mentally before editing'

    destructive_confirmation_step = 'See `<ASK_USER_TOOL>` to confirm scope and target'
    if checkpoints_on:
        checkpoint_step = 'After the change, verify immediately; if it fails, `checkpoint(revert)` or `undo_last_edit`'
    else:
        checkpoint_step = 'If approved, keep the change surface small and verify immediately after the action'
    adjacent_tool_fallback = (
        f'symbol lookup → {_tool_ref(GREP_TOOL_NAME)}; '
        f'{_tool_ref(CODE_INTELLIGENCE_TOOL_NAME)} → {_tool_ref(GREP_TOOL_NAME)}'
        if lsp_available
        else f'symbol lookup → {_tool_ref(GREP_TOOL_NAME)}; refine the query and read nearby files'
    )
    failure_escalation_step = (
        'After repeated failed attempts on the same sub-task, see `<ASK_USER_TOOL>` '
        'with a 1-line post-mortem and a specific question'
    )

    return render_partial(
        'system_partial_05_examples.md',
        available_tools_summary=available_tools_summary,
        search_tools=search_tools,
        edit_tools=edit_tools,
        read_tool=_tool_ref(READ_FILE_TOOL_NAME),
        analyze_tool=_tool_ref(ANALYZE_PROJECT_STRUCTURE_TOOL_NAME),
        multiedit_tool=_tool_ref(MULTIEDIT_TOOL_NAME),
        replace_string_tool=_tool_ref(REPLACE_STRING_TOOL_NAME),
        terminal_tool=_tool_ref(terminal_command_tool),
        planning_hint=planning_hint,
        destructive_confirmation_step=destructive_confirmation_step,
        checkpoint_step=checkpoint_step,
        adjacent_tool_fallback=adjacent_tool_fallback,
        failure_escalation_step=failure_escalation_step,
    )
