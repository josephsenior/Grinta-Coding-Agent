"""Renderer for the routing partial (system_partial_00_routing.md)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.engine.prompts.section_renderers._common import _semantic_recall_runtime
from backend.engine.prompts.section_renderers._env_hints import (
    _debugger_available,
    _discovery_decision_table,
    _lsp_available,
    _repo_discovery_contract,
    _routing_memory_tool_placeholders,
)


def _routing_env_line(
    is_windows: bool,
    windows_with_bash: bool,
    terminal_available: bool,
) -> str:
    if not terminal_available:
        return ''
    if not is_windows:
        return 'Use **bash** for environment actions (install, build, test, git, processes). '
    if windows_with_bash:
        return (
            'Use **bash** (Git Bash on Windows) for environment actions '
            '(install, build, test, git, processes). '
        )
    return 'Use **PowerShell** for environment actions (install, build, test, git, processes). '


def _routing_ladders(can_edit: bool, terminal_available: bool) -> tuple[str, str]:
    if not can_edit:
        return '', ''
    read_and_edit_ladder = (
        '- **Read & Edit:** Follow `<EDITOR_AND_FILE_OPERATIONS>` — '
        'do not use shell commands to write source files.'
    )
    shell_and_execution_ladder = (
        '- **Shell & Execution:** Use `terminal` for environment/runtime inspection, '
        'builds, tests, git, and process lifecycles. Use `<DISCOVERY_ROUTING>` for repository intelligence.'
        if terminal_available
        else ''
    )
    return read_and_edit_ladder, shell_and_execution_ladder


def _render_routing(
    render_partial: Callable[..., str],
    is_windows: bool,
    config: Any = None,
    function_calling_mode: str | None = None,
    *,
    windows_with_bash: bool = False,
    shell_is_powershell: bool = False,
    semantic_recall_active: bool | None = None,
) -> str:
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
        normalize_interaction_mode,
    )

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    can_edit = not (is_chat_mode(mode) or is_plan_mode(mode))
    terminal_available = bool(getattr(config, 'enable_terminal', True))

    lsp_available = _lsp_available(config)
    debugger_available = can_edit and _debugger_available(config)
    working_memory_on = getattr(config, 'enable_working_memory', True)
    tracker_on = getattr(config, 'enable_task_tracker_tool', True)
    criteria_on = getattr(config, 'enable_acceptance_criteria_tool', True)
    env_line = _routing_env_line(is_windows, windows_with_bash, terminal_available)
    discovery = _repo_discovery_contract(
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
    )
    if not terminal_available:
        discovery = (
            'Repo/source intelligence: follow `<DISCOVERY_ROUTING>` and use native '
            'read-only tools; no terminal tool is available in this runtime.'
        )
    batch_cmds = env_line + discovery
    lsp_routing = (
        '- **Known file + symbol position, precise definition/references/hover** → `lsp`'
        if lsp_available
        else ''
    )
    debugger_routing = (
        '- **Runtime bugs, stateful failures, control-flow uncertainty, or "why did this branch/value happen?"** -> `debugger` (set breakpoints, run/attach, inspect stack/scopes/variables, evaluate, step, then stop the session).'
        if debugger_available
        else ''
    )
    memory_kw = _routing_memory_tool_placeholders(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        criteria_on=criteria_on,
        semantic_recall_on=_semantic_recall_runtime(
            config, semantic_recall_active=semantic_recall_active
        ),
    )

    web_on = bool(getattr(config, 'enable_web', True))
    docs_on = bool(getattr(config, 'enable_docs', True))
    from backend.utils.optional_extras import browser_tool_enabled

    discovery_decision_table = _discovery_decision_table(
        lsp_available=lsp_available,
        web_on=web_on,
        docs_on=docs_on,
        browser_on=browser_tool_enabled(config) and can_edit,
    )

    read_and_edit_ladder, shell_and_execution_ladder = _routing_ladders(
        can_edit,
        terminal_available,
    )

    return render_partial(
        'system_partial_00_routing.md',
        ambiguous_intent_instruction=memory_kw['ambiguous_intent_instruction'],
        batch_commands=batch_cmds,
        lsp_routing=lsp_routing,
        debugger_routing=debugger_routing,
        discovery_decision_table=discovery_decision_table,
        memory_and_context_section=memory_kw['memory_and_context_section'],
        post_condensation_retrieval=memory_kw['post_condensation_retrieval'],
        remaining_work_source_of_truth=memory_kw['remaining_work_source_of_truth'],
        surviving_state_facts=memory_kw['surviving_state_facts'],
        read_and_edit_ladder=read_and_edit_ladder,
        shell_and_execution_ladder=shell_and_execution_ladder,
    )
