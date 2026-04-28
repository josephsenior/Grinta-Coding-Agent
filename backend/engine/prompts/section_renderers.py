"""Prompt section renderers shared by the system prompt builder."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.inference.provider_capabilities import (
    model_token_correction as _model_token_correction,
)


def _count_section_tokens(text: str, model_id: str) -> tuple[int, str]:
    """Best-effort token count for budgeting. Returns (tokens, encoding_label)."""
    try:
        import tiktoken  # type: ignore

        mid = (model_id or '').strip().lower()

        if mid:
            try:
                enc = tiktoken.encoding_for_model(mid)
                tokens = len(enc.encode(text))
                return tokens, f'model:{mid}'
            except Exception:
                pass

        enc = tiktoken.get_encoding('o200k_base')
        tokens = len(enc.encode(text))
        factor, label = _model_token_correction(model_id)
        if factor != 1.0:
            tokens = int(tokens * factor)
        return tokens, label
    except Exception:
        est = max(0, len(text) // 4)
        return est, 'chars_div_4_fallback'


def _choose(is_windows: bool, win: str, unix: str) -> str:
    return win if is_windows else unix


def _resolve_terminal_command_tool(
    is_windows: bool,
    terminal_tool_name: str | None,
) -> str:
    """Resolve the active terminal command tool for prompt rendering."""
    if terminal_tool_name:
        return terminal_tool_name
    return 'execute_powershell' if is_windows else 'execute_bash'


def _code_intelligence_available(config: Any = None) -> bool:
    """Return whether the code_intelligence tool should be considered available."""
    if not getattr(config, 'enable_lsp_query', False):
        return False
    try:
        from backend.utils.lsp_client import _detect_pylsp

        return bool(_detect_pylsp())
    except Exception:
        return False


def _explore_hint(_config: Any = None) -> str:
    """Return the canonical layout-discovery tool hint."""
    return (
        '`search_code` first, then `explore_tree_structure`; '
        'use `analyze_project_structure` only when needed'
    )


def _routing_tool_batching_paragraph(function_calling_mode: str | None) -> str:
    mode = (function_calling_mode or 'unknown').strip().lower()
    if mode == 'native':
        return (
            'Native function-calling mode is active. You may batch independent tool calls '
            'in one assistant turn when it improves latency; keep dependent calls sequential.'
        )
    if mode == 'string':
        return (
            'Fallback string-parsing mode is active. Emit exactly one tool call per assistant '
            'message and continue step-by-step.'
        )
    return (
        'Mode is unknown. Use conservative single tool-call turns unless runtime capability '
        'signals explicitly confirm native multi-call support.'
    )


def _routing_memory_tool_placeholders(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    condensation_on: bool,
    meta_cognition_on: bool,
) -> dict[str, str]:
    ambiguous_intent_instruction = (
        'Use `communicate_with_user` to offer options rather than guessing.'
        if meta_cognition_on
        else 'Ask the user a short clarifying question in natural language rather than guessing.'
    )
    if working_memory_on:
        memory_and_context_section = (
            '<MEMORY_AND_CONTEXT_TOOLS>\n'
            '- Disk facts: `note(key, value)` / `recall(key)`.\n'
            '- Session state: `memory_manager(action="working_memory", ...)` and `memory_manager(action="semantic_recall", key=...)`.\n'
            'Rule: long-lived facts → `note`; task-local state → `memory_manager`.\n'
            '</MEMORY_AND_CONTEXT_TOOLS>'
        )
        post_condensation_retrieval = (
            'Call `memory_manager(action="working_memory")` after condensation to restore plan/findings before acting.'
        )
        surviving_state_facts = (
            'Only `note` (disk) and `memory_manager` (session) facts reliably survive condensation.'
        )
    else:
        memory_and_context_section = (
            '<MEMORY_AND_CONTEXT_TOOLS>\n'
            '- Disk facts still use `note(key, value)` / `recall(key)`.\n'
            '- No structured within-session working-memory tool is available in this run; keep active hypotheses compact and rely on verified observations.\n'
            '</MEMORY_AND_CONTEXT_TOOLS>'
        )
        post_condensation_retrieval = (
            'Resume from the summary and your most recent verified observations; no structured working-memory tool is available in this run.'
        )
        surviving_state_facts = (
            'Only `note` (disk) facts are guaranteed to survive condensation.'
        )
    context_budget_sync_clause = ', sync `task_tracker`' if tracker_on else ''
    context_budget_next_step = (
        'call `finish` or `summarize_context`'
        if condensation_on
        else 'call `finish` or close the current sub-task before doing any broader exploration'
    )
    repetition_recovery_options = (
        'switch tools, escalate with `communicate_with_user`, or call `finish` with a partial result.'
        if meta_cognition_on
        else 'switch tools, ask the user a short clarifying question, or call `finish` with a partial result.'
    )
    remaining_work_source_of_truth = (
        'Trust your `task_tracker` plan as the source of truth for what remains.'
        if tracker_on
        else 'Use restored working memory and recent verified observations as the source of truth for what remains.'
    )
    return {
        'ambiguous_intent_instruction': ambiguous_intent_instruction,
        'memory_and_context_section': memory_and_context_section,
        'post_condensation_retrieval': post_condensation_retrieval,
        'surviving_state_facts': surviving_state_facts,
        'context_budget_sync_clause': context_budget_sync_clause,
        'context_budget_next_step': context_budget_next_step,
        'repetition_recovery_options': repetition_recovery_options,
        'remaining_work_source_of_truth': remaining_work_source_of_truth,
    }


def _render_routing(
    render_partial: Callable[..., str],
    is_windows: bool,
    config: Any = None,
    function_calling_mode: str | None = None,
) -> str:
    explore = _explore_hint(config)
    code_intelligence_available = _code_intelligence_available(config)
    meta_cognition_on = getattr(config, 'enable_meta_cognition', False)
    working_memory_on = getattr(config, 'enable_working_memory', True)
    condensation_on = getattr(config, 'enable_condensation_request', False)
    tracker_on = getattr(config, 'enable_internal_task_tracker', False)
    batch_cmds = _choose(
        is_windows,
        f'Use **PowerShell** only for environment actions (install, build, test, git, processes). '
        f'For repo layout and file content, use **{explore}** '
        'and **`text_editor` (`read_file`)**—not `Get-Content`/`Select-String` pipelines for source trees.',
        f'Use **bash** only for environment actions (install, build, test, git, processes). '
        f'For repo layout and file content, use **{explore}** '
        'and **`text_editor` (`read_file`)**—not `ls && cat && grep` chains for project files.',
    )
    code_intelligence_routing = (
        '- **Known file + symbol position, precise definition/references/hover** → `code_intelligence`'
        if code_intelligence_available
        else ''
    )
    tool_call_batching_mode = _routing_tool_batching_paragraph(function_calling_mode)
    memory_kw = _routing_memory_tool_placeholders(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        condensation_on=condensation_on,
        meta_cognition_on=meta_cognition_on,
    )
    return render_partial(
        'system_partial_00_routing.md',
        ambiguous_intent_instruction=memory_kw['ambiguous_intent_instruction'],
        batch_commands=batch_cmds,
        code_intelligence_routing=code_intelligence_routing,
        context_budget_sync_clause=memory_kw['context_budget_sync_clause'],
        context_budget_next_step=memory_kw['context_budget_next_step'],
        explore_layout_hint=explore,
        memory_and_context_section=memory_kw['memory_and_context_section'],
        post_condensation_retrieval=memory_kw['post_condensation_retrieval'],
        remaining_work_source_of_truth=memory_kw['remaining_work_source_of_truth'],
        repetition_recovery_options=memory_kw['repetition_recovery_options'],
        surviving_state_facts=memory_kw['surviving_state_facts'],
        tool_call_batching_mode=tool_call_batching_mode,
    )


def _render_security(cli_mode: bool = True) -> str:
    risk_block = (
        '- **LOW**: Safe, read-only actions.\n'
        '  - Viewing/summarizing content, reading project files, simple in-memory calculations.\n'
        '- **MEDIUM**: Project-scoped edits or execution.\n'
        '  - Modify user project files, run project scripts/tests, install project-local packages.\n'
        '- **HIGH**: System-level or untrusted operations.\n'
        '  - Changing system settings, global installs, elevated (`sudo`) commands, deleting critical files, '
        'downloading & executing untrusted code, or sending local secrets/data out.'
    )
    return (
        '# 🔐 Security Risk Policy\n'
        'When using tools that support the security_risk parameter, assess the safety risk of your actions:\n\n'
        f'{risk_block}\n\n'
        '**Global Rules**\n'
        '- Always escalate to **HIGH** if sensitive data leaves the environment.'
    )


def _render_autonomy(render_partial: Callable[..., str], config: Any, is_windows: bool) -> str:
    level = getattr(config, 'autonomy_level', 'balanced')
    checkpoints = getattr(config, 'enable_checkpoints', False)
    code_intelligence_available = _code_intelligence_available(config)
    cp_line = (
        " Auto-save occurs before large writes; use 'checkpoint' tool to manually save logically safe states."
        if checkpoints
        else ''
    )

    autonomy = ''
    if level == 'full':
        autonomy = (
            f'<AUTONOMY>\nFULL AUTONOMOUS MODE: Execute all planned steps end-to-end without '
            f'confirmation. On tool failure, pivot to an alternative tool in the same turn '
            f'(e.g. symbol_editor → text_editor). Auto-retry recoverable errors. '
            f'Report back only after completing the plan or exhausting tool alternatives on a '
            f'blocking sub-task. '
            f'{cp_line}\n</AUTONOMY>'
        )

    path_hint = _choose(
        is_windows,
        f'run {_explore_hint(config)}, or list with `Get-ChildItem` only if no tool fits',
        f'run {_explore_hint(config)}—avoid blind `cat` of guessed paths',
    )
    code_intelligence_fallback = (
        '- `search_code` returns nothing → try `code_intelligence`'
        if code_intelligence_available
        else '- `search_code` returns nothing → try alternate search terms, do not fall back to shell.'
    )
    tracker_on = getattr(config, 'enable_internal_task_tracker', False)
    if tracker_on:
        task_tracker_discipline_block = (
            '<TASK_TRACKING>\n'
            '**task_tracker**: For multi-step tasks, use `view` to inspect the plan and `update` to replace the full `task_list`.\n'
            'Allowed statuses: `todo`, `doing`, `done`, `skipped`, `blocked`.\n'
            '**Syncing**: Update the tracker as statuses change; piggyback updates when possible.\n'
            '**Completion (CRITICAL)**: Do NOT call `finish` if any steps are still in `todo` or `doing`.'
            '</TASK_TRACKING>'
        )
    else:
        task_tracker_discipline_block = ''

    base_workflow = (
        'Default loop: scope → reproduce → isolate → fix → verify.\n'
        'For debug/fix tasks, re-run the same reproducer when possible.'
    )
    if tracker_on:
        problem_solving_workflow_body = (
            base_workflow
            + '\n\nWith **task_tracker** enabled, treat **sync** as part of the loop: after verify, update the plan when progress changed.'
        )
        task_sync_instruction = (
            '**Task synchronization:** Update `task_tracker` to `done`, `skipped`, or `blocked` before attempting to finish.'
        )
    else:
        problem_solving_workflow_body = base_workflow
        task_sync_instruction = (
            '**Plan synchronization:** Keep your working memory and finish summary aligned with what was actually completed before attempting to finish.'
        )

    return render_partial(
        'system_partial_01_autonomy.md',
        autonomy_block=autonomy,
        task_tracker_discipline_block=task_tracker_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        code_intelligence_fallback=code_intelligence_fallback,
        problem_solving_workflow_body=problem_solving_workflow_body,
    )


def _render_tool_reference(
    render_partial: Callable[..., str],
    is_windows: bool,
    config: Any = None,
) -> str:
    explore = _explore_hint(config)
    confirm_cmd = _choose(
        is_windows,
        f'If unsure where a file lives, use {explore} before opening it—not only `Get-ChildItem`.',
        f'If unsure where a file lives, use {explore} before opening it—not only `ls`.',
    )
    proc_find = _choose(
        is_windows,
        "Find: `Get-Process | Where-Object { $_.ProcessName -like '*name*' }`; kill: `Stop-Process -Id <PID>`.",
        'Never `pkill -f` broadly — `ps`/`grep` then `kill <PID>`.',
    )
    checkpoints = getattr(config, 'enable_checkpoints', False)
    checkpoint_rollback_hint = (
        '; use **checkpoint** for coarse rollback'
        if checkpoints
        else ''
    )
    return render_partial(
        'system_partial_02_tools.md',
        confirm_paths=confirm_cmd,
        process_management=proc_find,
        checkpoint_rollback_hint=checkpoint_rollback_hint,
    )


def _render_critical(
    render_partial: Callable[..., str],
    terminal_command_tool: str,
    *,
    enable_think: bool,
    terminal_manager_available: bool,
    meta_cognition_on: bool,
) -> str:
    """Render last-mile critical execution rules with dynamic terminal tool naming."""
    think_execution_rule = (
        '**`think` does not execute** — after reasoning, you must still call tools.'
        if enable_think
        else '**Reasoning alone does not execute** — after reasoning, you must still call tools.'
    )
    if terminal_manager_available:
        terminal_manager_rule = (
            '**Interactive terminal discipline**:\n'
            '   - For `terminal_manager action=open`, reuse only the returned `session_id`; never invent one. The `open` command already runs; later commands use `action=input`.\n'
            '   - Prefer `action=read` with `mode=delta`; reuse `next_offset` or omit `offset`.\n'
            '   - If output stalls, stop repeating the same `read` / `input` / `control`; send a different command or pivot tools.\n'
            '   - Read an opened session before opening another similar one.\n'
            '   - If the latest user message is about your behavior rather than more terminal work, answer in natural language first.'
        )
    else:
        terminal_manager_rule = (
            f'**Interactive terminal sessions are unavailable in this run** — do not refer to `terminal_manager`; use `{terminal_command_tool}` for non-interactive command execution only.'
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
        user_question_antipattern=user_question_antipattern,
    )


def _render_examples(
    render_partial: Callable[..., str],
    *,
    tracker_on: bool,
    enable_think: bool,
    meta_cognition_on: bool,
    code_intelligence_available: bool,
    checkpoints_on: bool,
) -> str:
    """Render the worked-examples partial with capability-aware tool references."""
    if tracker_on and enable_think:
        planning_hint = 'draft the plan with `task_tracker` (or `think`)'
    elif tracker_on:
        planning_hint = 'draft the plan with `task_tracker`'
    elif enable_think:
        planning_hint = 'draft the plan with `think`'
    else:
        planning_hint = 'draft a short plan in your working notes before editing'

    destructive_confirmation_step = (
        'Use `communicate_with_user` to confirm scope and target.'
        if meta_cognition_on
        else 'ask the user a short clarifying question in natural language to confirm scope and target.'
    )
    checkpoint_step = (
        'If approved and supported, take a `checkpoint` first.'
        if checkpoints_on
        else 'If approved, keep the change surface small and verify immediately after the action.'
    )
    adjacent_tool_fallback = (
        '`symbol_editor` → `text_editor`; `code_intelligence` → `search_code`'
        if code_intelligence_available
        else '`symbol_editor` → `text_editor`; refine the `search_code` query and read nearby files'
    )
    failure_escalation_step = (
        'After 3 failed attempts on the same sub-task, escalate via `communicate_with_user` with a 1-line post-mortem and a specific question.'
        if meta_cognition_on
        else 'After 3 failed attempts on the same sub-task, ask the user with a 1-line post-mortem and a specific question.'
    )
    return render_partial(
        'system_partial_05_examples.md',
        planning_hint=planning_hint,
        destructive_confirmation_step=destructive_confirmation_step,
        checkpoint_step=checkpoint_step,
        adjacent_tool_fallback=adjacent_tool_fallback,
        failure_escalation_step=failure_escalation_step,
    )


def _permission_git_summary(perm: Any) -> tuple[str, str]:
    git_parts: list[str] = []
    if getattr(perm, 'git_enabled', False):
        if getattr(perm, 'git_allow_commit', False):
            git_parts.append('COMMIT')
        if getattr(perm, 'git_allow_push', False):
            git_parts.append('PUSH')
        if getattr(perm, 'git_allow_force_push', False):
            git_parts.append('FORCE')
        if getattr(perm, 'git_allow_branch_delete', False):
            git_parts.append('DELETE-BRANCH')
        git_str = ' '.join(git_parts) or 'ENABLED'
    else:
        git_str = 'DISABLED'
    git_protected = ', '.join(getattr(perm, 'git_protected_branches', []))
    return git_str, git_protected


def _permission_shell_network_limits(perm: Any) -> tuple[str, str, str, str]:
    shell_str = 'ENABLED' if getattr(perm, 'shell_enabled', False) else 'DISABLED'
    if getattr(perm, 'shell_enabled', False) and getattr(perm, 'shell_allow_sudo', False):
        shell_str += ' + SUDO'
    shell_blocked = ', '.join(getattr(perm, 'shell_blocked_commands', []))

    net_str = 'DISABLED'
    if getattr(perm, 'network_enabled', False):
        net_str = f'{getattr(perm, "network_max_requests_per_minute", "?")}/min'
        domains = getattr(perm, 'network_allowed_domains', [])
        if domains:
            net_str += f' | Only: {", ".join(domains)}'

    max_writes = getattr(perm, 'max_file_writes_per_task', '?')
    max_cmds = getattr(perm, 'max_shell_commands_per_task', '?')
    cost = getattr(perm, 'max_cost_per_task', None)
    limits = f'{max_writes} files, {max_cmds} commands'
    if cost:
        limits += f', ${cost} cost'

    return shell_str, shell_blocked, net_str, limits


def _render_permissions(config: Any, perm: Any) -> str:
    """Render the <PERMISSIONS> block from config.permissions."""
    file_w = 'WRITE' if getattr(perm, 'file_write_enabled', False) else 'READ-ONLY'
    if getattr(perm, 'file_write_enabled', False):
        file_w += f' (max {getattr(perm, "file_operations_max_size_mb", "?")}MB)'
    file_d = 'DELETE' if getattr(perm, 'file_delete_enabled', False) else 'NO DELETE'
    blocked = ', '.join(getattr(perm, 'file_operations_blocked_paths', []))

    git_str, git_protected = _permission_git_summary(perm)
    shell_str, shell_blocked, net_str, limits = _permission_shell_network_limits(perm)

    return (
        '<PERMISSIONS>\n'
        f'**File:** {file_w} | {file_d}\n'
        f'Blocked: {blocked}\n\n'
        f'**Git:** {git_str}\n'
        f'Protected: {git_protected}\n\n'
        f'**Shell:** {shell_str}\n'
        f'Blocked: {shell_blocked}\n\n'
        f'**Network:** {net_str}\n\n'
        f'**Limits:** {limits}/task\n\n'
        'Exceeding permissions → Error. Work within limits or request permission.\n'
        '</PERMISSIONS>'
    )


def _append_mcp_connected_catalog_sections(
    parts: list[str],
    mcp_tool_names: list[str],
    mcp_tool_descriptions: dict[str, str],
    mcp_server_hints: list[dict[str, str]],
) -> None:
    total = len(mcp_tool_names)
    parts.extend(
        (
            f'🔌 **External MCP tools** ({total}): use **`call_mcp_tool(tool_name="...", arguments={{...}})`** '
            f'— argument shapes match the registered tool schema.',
            '**Tool-name discipline (critical):** Pass each tool name to '
            '`call_mcp_tool(tool_name=...)` **exactly as listed below** — the names '
            'are already flat. Do **not** add `server:`, `server/`, `server.`, '
            '`server__` or any other prefix; those are not part of the name and '
            'will fail. If a name you want is not in this list, that tool is '
            'not available in this session — pick a different tool or an '
            'alternative approach. Do not guess.',
        )
    )
    for name in mcp_tool_names:
        parts.append(f'- `{name}`: {mcp_tool_descriptions[name]}')

    if mcp_server_hints:
        parts.extend(
            (
                '',
                '<MCP_SERVER_HINTS>',
                '**Configured MCP servers (when to use each — from your MCP settings):**',
            )
        )
        for row in mcp_server_hints:
            parts.append(f'- **`{row["server"]}`:** {row["hint"]}')
        parts.append('</MCP_SERVER_HINTS>')

    parts.extend(('', '<MCP_WHEN_TO_USE>', '**Discipline (MCP):**'))
    if mcp_server_hints:
        parts.append(
            "Follow **Configured MCP servers** above for *when* to prefer each server; "
            "match the user's task to those hints, then pick the concrete tool name from the list "
            "and each tool's description."
        )
    else:
        parts.append(
            "Infer *when* to call MCP from each tool's **name** and **description** in the list above "
            "(and avoid training-memory guesses for vendor-specific or version-specific facts—use a tool when one fits)."
        )
    parts.extend(
        (
            'Prefer **`call_mcp_tool`** over shell one-offs when an MCP tool covers the need. '
            'If asked what you can do or which models/tools you have, answer from **this** tool list, '
            '**MCP server hints** (if any), and your configured model id—**not** generic "no web / no docs" tropes.',
            '</MCP_WHEN_TO_USE>',
        )
    )


def _mcp_tail_render_kwargs(
    render_partial: Callable[..., str],
    config: Any,
) -> str:
    meta_cognition = getattr(config, 'enable_meta_cognition', False)
    enable_think = bool(getattr(config, 'enable_think', False))
    communicate_tool_section = (
        '<COMMUNICATE_TOOL>\n'
        'Use `communicate_with_user` for clarification, uncertainty, risky-action options, or escalation after 3 failed attempts on a sub-task. On escalation, include a brief post-mortem and one specific question. Do not ask mid-task questions in plain text; use this tool so the turn ends cleanly and waits for user input.\n'
        '</COMMUNICATE_TOOL>'
        if meta_cognition
        else ''
    )
    code_intelligence_available = _code_intelligence_available(config)
    if code_intelligence_available:
        uncertainty_state_1_discover_line = (
            '**Can be discovered** (unknown path, API, or config shape) → follow **TOOL_ROUTING_LADDER**; use tools like `search_code`, editor `view_*`, or `code_intelligence`. Do NOT ask first.'
        )
    else:
        uncertainty_state_1_discover_line = (
            '**Can be discovered** (unknown path, API, or config shape) → follow **TOOL_ROUTING_LADDER**, not shell repo search/read. Do NOT ask first.'
        )
    thinking_tool_section = (
        '<THINKING_TOOL>\n'
        'Use `think` for multi-step planning, complex debugging, or architecture trade-offs. It records reasoning only; it does not execute actions.\n'
        '</THINKING_TOOL>'
        if enable_think
        else ''
    )
    return render_partial(
        'system_partial_03_tail.md',
        communicate_tool_section=communicate_tool_section,
        interaction_guidance=(
            'If a request is vague, inspect nearby docs/config first; use `communicate_with_user` only if you are still blocked or the scope is still ambiguous.'
            if meta_cognition
            else 'If a request is vague, inspect nearby docs/config first; ask the user directly in natural language only if you are still blocked or the scope is still ambiguous.'
        ),
        uncertainty_state_1_discover_line=uncertainty_state_1_discover_line,
        uncertainty_state_2_ambiguous_line=(
            '**Ambiguous intent** (multiple valid implementations, destructive action, unclear scope) → `communicate_with_user` with `options`. Do NOT guess.'
            if meta_cognition
            else '**Ambiguous intent** (multiple valid implementations, destructive action, unclear scope) → ask the user a short clarifying question in natural language. Do NOT guess.'
        ),
        uncertainty_state_3_unknowable_line=(
            "**Needs user input** (user preference, external credential, business policy) → `communicate_with_user` with `intent='clarification'`."
            if meta_cognition
            else '**Needs user input** (user preference, external credential, business policy) → ask the user directly in natural language.'
        ),
        thinking_tool_section=thinking_tool_section,
    )


def _render_mcp_and_permissions(
    render_partial: Callable[..., str],
    mcp_tool_names: list[str],
    mcp_tool_descriptions: dict[str, str],
    mcp_server_hints: list[dict[str, str]],
    config: Any,
) -> str:
    parts: list[str] = ['<MCP_TOOLS>']

    if mcp_tool_names:
        _append_mcp_connected_catalog_sections(
            parts,
            mcp_tool_names,
            mcp_tool_descriptions,
            mcp_server_hints,
        )
    else:
        parts.append('No external MCP tools connected.')
    parts.append('</MCP_TOOLS>')

    if getattr(config, 'enable_permissions', False):
        perm = getattr(config, 'permissions', None)
        if perm is not None:
            parts.extend(('', _render_permissions(config, perm)))

    parts.extend(('', _mcp_tail_render_kwargs(render_partial, config)))

    return '\n'.join(parts)