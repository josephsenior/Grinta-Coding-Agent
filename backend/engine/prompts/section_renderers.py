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


def _lsp_available(config: Any = None) -> bool:
    """Return whether the lsp tool should be considered available."""
    if not getattr(config, 'enable_lsp_query', True):
        return False
    try:
        from backend.utils.runtime_detect import has_any_lsp_server

        return bool(has_any_lsp_server())
    except Exception:
        return False


def _explore_hint(_config: Any = None) -> str:
    """Return the canonical layout-discovery tool hint."""
    if _lsp_available(_config):
        return (
            '`search_code` for text search, `find_symbols` for symbol candidates, '
            '`read` to fetch a specific symbol/file body, `lsp` for definitions/references '
            '(LSP), `analyze_project_structure` for tree layout'
        )
    return (
        '`search_code` for text search, `find_symbols` for symbol candidates, `read` to fetch a '
        'specific symbol/file body, `analyze_project_structure` for tree layout'
    )


def _repo_discovery_contract(
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    """One line: prefer ladder tools for repo intelligence; shell details live in SHELL_IDENTITY."""
    if not is_windows:
        return (
            'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` and use '
            '`read`—avoid improvised `find`/`grep`/`cat` tree walks; '
            '`<SHELL_IDENTITY>` governs allowed shell usage.'
        )
    if windows_with_bash:
        return (
            'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` and editors first; '
            'terminal is Git Bash under `<SHELL_IDENTITY>`.'
        )
    if shell_is_powershell:
        return (
            'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` and editors first; '
            'do not use Unix-only shell habits in PowerShell—see `<SHELL_IDENTITY>`.'
        )
    return (
        'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` first; '
        'see `<SHELL_IDENTITY>` for shell-specific rules.'
    )


def _path_uncertainty_hint(
    explore: str,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    """Short ERROR_RECOVERY path line; defers anti-pattern lists to SHELL_IDENTITY."""
    if not is_windows:
        return (
            f'When paths are uncertain: use {explore}; boundaries in '
            '`<TOOL_ROUTING_LADDER>` + `<SHELL_IDENTITY>`.'
        )
    if windows_with_bash:
        return f'When paths are uncertain: use {explore}; Git Bash rules in `<SHELL_IDENTITY>`.'
    if shell_is_powershell:
        return f'When paths are uncertain: use {explore}; PowerShell rules in `<SHELL_IDENTITY>`.'
    return f'When paths are uncertain: use {explore}; see `<SHELL_IDENTITY>`.'


def _routing_tool_batching_paragraph(function_calling_mode: str | None) -> str:
    mode = (function_calling_mode or 'unknown').strip().lower()
    if mode == 'native':
        return 'You may batch independent code search/reads in one turn if it improves latency. Dependent edits/runs must be sequential.'
    if mode == 'string':
        return 'Fallback string-parsing mode is active. Only emit one tool call per message.'
    return 'Use single tool-calls unless multi-call is clearly supported.'


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
            '- Disk facts: `note(key, value)` / `recall(key)`. Use for long-lived facts (e.g., user preferences, architectural rules, common commands).\n'
            '- Session state: `memory_manager(action="working_memory", ...)` and `memory_manager(action="semantic_recall", key=...)`. Use for ephemeral task-local state (e.g., current bug hypotheses, "step 2 of 5").\n'
            '- **Auto-sync**: Scratchpad notes are automatically synced to working_memory at session start and after condensation. No manual sync needed.\n'
            'Rule: cross-session knowledge → `note`; within-session state → `memory_manager`.\n'
            '</MEMORY_AND_CONTEXT_TOOLS>'
        )
        post_condensation_retrieval = 'Call `memory_manager(action="working_memory")` after condensation to restore plan/findings before acting.'
        surviving_state_facts = 'Only `note` (disk) and `memory_manager` (session) facts reliably survive condensation.'
    else:
        memory_and_context_section = ''
        post_condensation_retrieval = 'Resume from the summary and your most recent verified observations.'
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
    *,
    windows_with_bash: bool = False,
    shell_is_powershell: bool = False,
) -> str:
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
        normalize_interaction_mode,
    )
    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    can_edit = not (is_chat_mode(mode) or is_plan_mode(mode))

    explore = _explore_hint(config)
    lsp_available = _lsp_available(config)
    meta_cognition_on = getattr(config, 'enable_meta_cognition', False)
    working_memory_on = getattr(config, 'enable_working_memory', True)
    condensation_on = getattr(config, 'enable_condensation_request', False)
    tracker_on = getattr(config, 'enable_task_tracker_tool', False)
    if not is_windows:
        env_line = 'Use **bash** for environment actions (install, build, test, git, processes). '
    elif windows_with_bash:
        env_line = (
            'Use **bash** (Git Bash on Windows) for environment actions '
            '(install, build, test, git, processes). '
        )
    else:
        env_line = 'Use **PowerShell** for environment actions (install, build, test, git, processes). '
    discovery = _repo_discovery_contract(
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
    )
    batch_cmds = env_line + discovery
    lsp_routing = (
        '- **Known file + symbol position, precise definition/references/hover** → `lsp`'
        if lsp_available
        else ''
    )
    tool_call_batching_mode = _routing_tool_batching_paragraph(function_calling_mode)
    memory_kw = _routing_memory_tool_placeholders(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        condensation_on=condensation_on,
        meta_cognition_on=meta_cognition_on,
    )

    if not can_edit:
        read_and_edit_ladder = ''
        shell_and_execution_ladder = ''
    else:
        read_and_edit_ladder = (
            '- **Read & Edit:** Use native tool calls only. `find_symbols` discovers symbol candidates; `read` inspects file/range/symbol content; `create` creates new files/symbols; `edit_symbols` modifies/deletes existing symbols; `replace_string` performs exact one-file text replacement/addition/deletion; `multiedit` performs atomic multi-file refactors with `replace_string` and `edit_symbols` operations.\n'
            '- **Edit scope:** Prefer the smallest intent-level operation that solves the problem. Do not use shell commands to write source files.\n'
            '- **NORMAL MODE:** Use the registered file tools only; do not invent alternate file-edit formats or serialized code payloads.'
        )
        shell_and_execution_ladder = '- **Shell & Execution:** Use the terminal strictly for build/test/git/processes.'

    return render_partial(
        'system_partial_00_routing.md',
        ambiguous_intent_instruction=memory_kw['ambiguous_intent_instruction'],
        batch_commands=batch_cmds,
        lsp_routing=lsp_routing,
        context_budget_sync_clause=memory_kw['context_budget_sync_clause'],
        context_budget_next_step=memory_kw['context_budget_next_step'],
        explore_layout_hint=explore,
        memory_and_context_section=memory_kw['memory_and_context_section'],
        post_condensation_retrieval=memory_kw['post_condensation_retrieval'],
        remaining_work_source_of_truth=memory_kw['remaining_work_source_of_truth'],
        repetition_recovery_options=memory_kw['repetition_recovery_options'],
        surviving_state_facts=memory_kw['surviving_state_facts'],
        tool_call_batching_mode=tool_call_batching_mode,
        read_and_edit_ladder=read_and_edit_ladder,
        shell_and_execution_ladder=shell_and_execution_ladder,
    )


def _render_system_capabilities(
    config: Any,
    *,
    function_calling_mode: str | None,
    parallel_tool_calls_provider_flag: bool,
) -> str:
    """Runtime-truth capability statement.

    This block exists so the agent can never lie about its own runtime behavior.
    Every bullet is derived from a live config flag or runtime check — do NOT
    add aspirational text here. If you change a default, this block updates
    automatically on the next prompt assembly.
    """
    parallel_enabled = bool(getattr(config, 'enable_parallel_tool_scheduling', False))
    checkpoints_on = bool(getattr(config, 'enable_checkpoints', False))
    fc_mode = (function_calling_mode or 'unknown').strip().lower()

    if parallel_enabled and parallel_tool_calls_provider_flag and fc_mode == 'native':
        parallel_line = (
            '- **Parallel tool scheduling**: ENABLED for read-only batches '
            '(`read`, `search_code`, `lsp`).\n'
            '  - **Usage**: Emitting multiple tool_calls in one assistant message is supported. '
            'Emit independent reads in a single assistant turn to run them concurrently.\n'
            '  - **Constraint**: Writes, edits, and shell commands always run sequentially.'
        )
        provider_line = ''
    else:
        parallel_line = (
            '- **Parallel tool calls**: NOT SUPPORTED by this model/run. '
            'Emit exactly ONE tool call per assistant turn. '
            'Batching multiple tool calls will cause errors.'
        )
        provider_line = ''

    condensation_line = (
        '- **Conversation condensation**: AUTOMATIC and middleware-driven. '
        'It costs ZERO tool calls and ZERO turns from your budget. '
        'It uses a 3-tier memory model (working / episodic / semantic) and re-injects a pre-condensation '
        'snapshot after pruning, so verified facts and the immediate task surface survive. '
        'Do not describe condensation as "lossy" or as something you must invoke manually.'
    )

    checkpoint_line = (
        '- **Checkpoints**: AVAILABLE for coarse-grained rollback of file/edit state. '
        'Take one before risky multi-step edits when atomic batch tools are not a fit. '
        '`checkpoint(command="view")` auto-detects modified files from workspace snapshots — no need to manually specify `files_modified`.'
        if checkpoints_on
        else ''
    )

    fc_line = f'- **Function-calling mode**: `{fc_mode}`.'

    # Runtime-detected language servers / debug adapters — only when those tools
    # are enabled in config (omit bullets entirely when gated off).
    lsp_line, dap_line = _render_runtime_detection_lines(config)
    detection_block = '\n'.join(line for line in (lsp_line, dap_line) if line)
    runtime_discovery_hint = (
        '\nIn particular, **never run shell commands like `Get-Command`/`which`/`where` '
        'to discover language servers or debug adapters** — the bullets in this section '
        'for those tools are the authoritative answer.'
        if detection_block
        else ''
    )

    parts = [
        '# 🧭 System Capabilities (verified at runtime)\n'
        'The following statements are derived from live config and feature flags. '
        'Treat them as authoritative — do not contradict them in user-facing replies.'
        f'{runtime_discovery_hint}\n\n'
        f'{parallel_line}\n'
        f'{provider_line}\n'
        f'{condensation_line}\n'
    ]
    if checkpoint_line:
        parts.append(f'{checkpoint_line}\n')
    parts.append(f'{fc_line}\n')
    if detection_block:
        parts.append(detection_block)

    return '\n'.join(parts)


def _render_runtime_detection_lines(config: Any) -> tuple[str, str]:
    r"""Return ``(lsp_line, dap_line)`` summarizing detected runtimes.

    When ``enable_lsp_query`` / ``enable_debugger`` is false, returns ``''`` for that
    line so the capability block omits the tool entirely (no \"DISABLED\" bullet).
    """
    lsp_enabled = bool(getattr(config, 'enable_lsp_query', True))
    debugger_enabled = bool(getattr(config, 'enable_debugger', False))
    try:
        from backend.utils.runtime_detect import (
            detection_summary,
            has_any_debug_adapter,
            has_any_lsp_server,
        )

        any_lsp = bool(has_any_lsp_server()) if lsp_enabled else False
        any_dap = bool(has_any_debug_adapter()) if debugger_enabled else False
        summary = (
            detection_summary()
            if (any_lsp or any_dap)
            else {
                'lsp_available': [],
                'debug_available': [],
            }
        )
    except Exception:
        any_lsp = False
        any_dap = False
        summary = {'lsp_available': [], 'debug_available': []}

    lsp_available = summary.get('lsp_available', []) if any_lsp else []
    if not lsp_enabled:
        lsp_line = ''
    elif lsp_available:
        lsp_line = (
            '- **Language servers (LSP / `lsp`)**: detected on PATH → '
            f'{", ".join(lsp_available)}. Use `lsp` for definition / '
            'references / hover / diagnostics on these languages. '
            'For file edits use the public file API tools; `lsp` is read-only. For file reads use `read`.'
        )
    else:
        lsp_line = ''

    if not debugger_enabled:
        dap_line = ''
    else:
        debug_available = summary.get('debug_available', []) if any_dap else []
        if debug_available:
            dap_line = (
                '- **Debug adapters (DAP / `debugger`)**: detected → '
                f'{", ".join(debug_available)}. The `debugger` tool resolves the right '
                'adapter automatically from the file extension or `adapter` field; do not '
                'pass `adapter_command` unless you have a custom binary.'
            )
        else:
            dap_line = ''
    return lsp_line, dap_line


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
        '`security_risk` is **required** on every call to `execute_bash`/`execute_powershell`, '
        '`browser`, and the file tools `read`, `find_symbols`, `create`, `replace_string`, `edit_symbols`, and `multiedit`. '
        'Pick one of `LOW` / `MEDIUM` / `HIGH` based on the action you are about to take. '
        'The server may escalate your risk label; it never lowers it. Missing or invalid values '
        'fail the call.\n\n'
        f'{risk_block}\n\n'
        '**Global Rules**\n'
        '- Always escalate to **HIGH** if sensitive data leaves the environment.\n'
        '- Long-running shell commands: pass an explicit `timeout` (seconds) instead of '
        'guessing.\n'
        '- For servers and log tails, use `is_background=true` on shell executors.\n'
        '- Interactive terminals (`terminal_manager`): wait for response before sending identical inputs.'
    )


def _build_context_discipline_section(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
    condensation_on: bool,
) -> str:
    parts = ['<CONTEXT_DISCIPLINE>']
    parts.append(
        'You have persistent context tools. Use them — context condensation is free '
        'and silent; relying only on attention-backed context guarantees information loss.'
    )

    # note/recall are always available — unconditional include
    parts.extend([
        '',
        '**note/recall** — facts that must survive across turns and new tasks:',
        '- Decision made, constraint discovered, or secret revealed \u2192 note() immediately.',
        '- Workspace architecture, DB URL, port mapping, test command \u2192 note().',
        "- recall(key='all') at session start to re-ground; never recall 'lessons' twice this session.",
    ])

    if working_memory_on:
        parts.extend([
            '',
            '**memory_manager** — your structured cognitive workspace for the current session:',
            "- update section='hypothesis' when you form a theory; update 'findings' when you have evidence.",
            "- update section='blockers' when something is stuck; update 'decisions' at each architectural pivot.",
            '- Call memory_manager(get) before context re-reads you might skip.',
        ])

    if tracker_on:
        parts.extend([
            '',
            '**task_tracker** — your structural anchor:',
            '- task_tracker(update) with the full plan before starting engineering work.',
            "- Update status \u2192 'doing' when starting, 'done' after proof, 'blocked' with reason.",
            '- For multi-step tasks: task_tracker(view) at turn start to re-anchor.',
        ])
        if condensation_on:
            if working_memory_on:
                parts.append('  Post-condensation: task_tracker(view) first, then memory_manager(get) + scratchpad.')
            else:
                parts.append('  Post-condensation: task_tracker(view) first, then scratchpad.')

    if checkpoints_on:
        parts.extend([
            '',
            '**checkpoint** — before risky multi-file edits or destructive shell operations.',
            'Do not edit in batches without one; checkpoint.save.name="batch before X".',
        ])

    parts.append('</CONTEXT_DISCIPLINE>')
    return '\n'.join(parts)


def _build_when_to_use_context(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
) -> str:
    parts = ['<WHEN_TO_USE_CONTEXT>']
    parts.append('- **note/recall**: Cross-turn persistence for facts, decisions, and discoveries.')
    if working_memory_on:
        parts.append('- **memory_manager**: In-session structured workspace for hypotheses, blockers, findings, and decisions.')
    if tracker_on:
        parts.append('- **task_tracker**: Engineering work planning and progress tracking — update before multi-step tasks, view at turn start.')
    if checkpoints_on:
        parts.append('- **checkpoint**: Before destructive or multi-file batch operations — save state so you can rollback.')
    parts.append('</WHEN_TO_USE_CONTEXT>')
    return '\n'.join(parts)


def _build_mandatory_discipline_checkpoints(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
) -> str:
    parts = ['<MANDATORY_DISCIPLINE_CHECKPOINTS>']
    # Session start is always relevant
    items = ["1. Session start \u2192 recall(key='all')"]
    idx = 2
    if tracker_on:
        items.append(f"{idx}. For multi-step tasks \u2192 task_tracker(update) with full plan")
        idx += 1
        items.append(f"{idx}. At turn start during multi-step work \u2192 task_tracker(view)")
        idx += 1
    if checkpoints_on:
        items.append(f"{idx}. Before destructive ops \u2192 checkpoint.save")
        idx += 1
    items.append(f"{idx}. On decision/pivot/discovery \u2192 note() or{' memory_manager(update) or' if working_memory_on else ''} note()")
    parts.extend(items)
    parts.append('</MANDATORY_DISCIPLINE_CHECKPOINTS>')
    return '\n'.join(parts)


def _build_risk_preview(
    *,
    tracker_on: bool,
) -> str:
    if not tracker_on:
        return ''
    return (
        '<RISK_PREVIEW>\n'
        'Before the **second** substantive milestone in one task (e.g. moving from core implementation work to tests or full build), '
        'or when **task_tracker** shows **more than one** non-`done` item you still intend to touch: write **two** concrete failure '
        'modes you could hit next (e.g. wrong public API vs wrong file; context loss between steps). '
        'After each major milestone, one line: *did a predicted failure happen?* If yes, pivot using `<ERROR_RECOVERY>` above — '
        'do not repeat the same failing move unchanged.\n'
        '</RISK_PREVIEW>'
    )


def _build_autonomy_block(mode: str, *, checkpoints_on: bool) -> str:
    cp_line = (
        " Auto-save occurs before large writes; use 'checkpoint' tool to manually save logically safe states."
        if checkpoints_on
        else ''
    )
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
    )
    if is_chat_mode(mode):
        return (
            '<AUTONOMY>\n'
            'Answer conversationally. Use tools only when investigation is needed. '
            'Do not mutate files or run mutating commands without explicit user request.'
            f'{cp_line}\n</AUTONOMY>'
        )
    if is_plan_mode(mode):
        return (
            '<AUTONOMY>\n'
            'Inspect and produce a structured plan. Do not mutate files. '
            'Do not run mutating commands. Finish with a plan covering the approach, '
            'files to change, risks, and verification steps.'
            f'{cp_line}\n</AUTONOMY>'
        )
    return (
        '<AUTONOMY>\n'
        "Plan, execute, and verify the user's task end-to-end. The runtime may "
        'interrupt a tool call to surface a user decision; treat that decision as '
        'authoritative and continue from where you stopped. On tool failure, make '
        'the next action a corrected retry or a different tool (e.g. `read` \u2192 `edit_symbols`, '
        'or `read` \u2192 `replace_string`) and auto-retry recoverable errors before reporting back.'
        f'{cp_line}\n</AUTONOMY>'
    )


def _render_autonomy(
    render_partial: Callable[..., str],
    config: Any,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    from backend.core.interaction_modes import (
        normalize_interaction_mode,
    )
    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    checkpoints_on = bool(getattr(config, 'enable_checkpoints', False))
    working_memory_on = bool(getattr(config, 'enable_working_memory', True))
    condensation_on = bool(getattr(config, 'enable_condensation_request', False))
    tracker_on = bool(getattr(config, 'enable_task_tracker_tool', False))

    autonomy_block = _build_autonomy_block(mode, checkpoints_on=checkpoints_on)
    context_discipline = _build_context_discipline_section(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
        condensation_on=condensation_on,
    )
    when_to_use_context = _build_when_to_use_context(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
    )
    mandatory_discipline_checkpoints = _build_mandatory_discipline_checkpoints(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
    )
    risk_preview = _build_risk_preview(tracker_on=tracker_on)

    explore = _explore_hint(config)
    path_hint = _path_uncertainty_hint(
        explore,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
    )
    if tracker_on:
        task_tracker_discipline_block = (
            '<TASK_TRACKING>\n'
            '**task_tracker**: For multi-step tasks, use `view` to inspect the plan and `update` to replace the full `task_list`.\n'
            'Quick status updates: use `update_status(task_id="...", status="done")` to change a single task without re-emitting the full list. Optional `result` field captures outcome.\n'
            'Allowed statuses: `todo`, `doing`, `done`, `skipped`, `blocked`.\n'
            '**Completion**: Put waiting tasks to `blocked` before calling `finish`.'
            '</TASK_TRACKING>'
        )
    else:
        task_tracker_discipline_block = ''

    base_workflow = (
        'Default loop: scope \u2192 reproduce \u2192 isolate \u2192 fix \u2192 verify.\n'
        'For debug/fix tasks, re-run the same reproducer when possible.'
    )
    if tracker_on:
        problem_solving_workflow_body = (
            base_workflow
            + '\n\nWith **task_tracker** enabled, treat **sync** as part of the loop: after verify, update the plan when progress changed.'
        )
        task_sync_instruction = '**Task synchronization:** Update `task_tracker` to `done`, `skipped`, or `blocked` before attempting to finish.'
    else:
        problem_solving_workflow_body = base_workflow
        task_sync_instruction = '**Plan synchronization:** Keep your working memory and finish summary aligned with what was actually completed before attempting to finish.'

    lsp_avail = _lsp_available(config)
    error_recovery_pivot_lines = (
            '- `search_code` \u2192 `lsp` (check locally with the language server; no shell grep)\n'
            '- `lsp` \u2192 `search_code` (wider text search)'
        if lsp_avail
        else ''
    )

    return render_partial(
        'system_partial_01_autonomy.md',
        autonomy_block=autonomy_block,
        context_discipline=context_discipline,
        when_to_use_context=when_to_use_context,
        mandatory_discipline_checkpoints=mandatory_discipline_checkpoints,
        risk_preview=risk_preview,
        task_tracker_discipline_block=task_tracker_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        problem_solving_workflow_body=problem_solving_workflow_body,
        error_recovery_pivot_lines=error_recovery_pivot_lines,
    )

    # Single mode-agnostic instruction. The runtime confirmation gate decides
    # whether to interrupt for user confirmation based on the configured autonomy
    # level — the agent should not branch on that knob in its prompt logic,
    # because the prompt would be wrong as soon as the user toggles modes
    # mid-session via /autonomy. Treat any user decision surfaced by the
    # gate as authoritative and continue from where you stopped.
    autonomy = (
        '<AUTONOMY>\n'
        "Plan, execute, and verify the user's task end-to-end. The runtime may "
        'interrupt a tool call to surface a user decision; treat that decision as '
        'authoritative and continue from where you stopped. On tool failure, pivot '
        'to an alternative tool in the same turn (e.g. `read` \u2192 `edit_symbols`, or `read` \u2192 `replace_string`) '
        'and auto-retry recoverable errors before reporting back.'
        f'{cp_line}\n</AUTONOMY>'
    )

    explore = _explore_hint(config)
    path_hint = _path_uncertainty_hint(
        explore,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
    )
    tracker_on = getattr(config, 'enable_task_tracker_tool', False)
    if tracker_on:
        task_tracker_discipline_block = (
            '<TASK_TRACKING>\n'
            '**task_tracker**: For multi-step tasks, use `view` to inspect the plan and `update` to replace the full `task_list`.\n'
            'Quick status updates: use `update_status(task_id="...", status="done")` to change a single task without re-emitting the full list. Optional `result` field captures outcome.\n'
            'Allowed statuses: `todo`, `doing`, `done`, `skipped`, `blocked`.\n'
            '**Completion**: Put waiting tasks to `blocked` before calling `finish`.'
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
        task_sync_instruction = '**Task synchronization:** Update `task_tracker` to `done`, `skipped`, or `blocked` before attempting to finish.'
    else:
        problem_solving_workflow_body = base_workflow
        task_sync_instruction = '**Plan synchronization:** Keep your working memory and finish summary aligned with what was actually completed before attempting to finish.'

    lsp_avail = _lsp_available(config)
    error_recovery_pivot_lines = (
            '- `search_code` \u2192 `lsp` (check locally with the language server; no shell grep)\n'
            '- `lsp` \u2192 `search_code` (wider text search)'
        if lsp_avail
        else ''
    )

    return render_partial(
        'system_partial_01_autonomy.md',
        autonomy_block=autonomy,
        task_tracker_discipline_block=task_tracker_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        problem_solving_workflow_body=problem_solving_workflow_body,
        error_recovery_pivot_lines=error_recovery_pivot_lines,
    )


def _render_tool_reference(
    render_partial: Callable[..., str],
    config: Any = None,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
        normalize_interaction_mode,
    )
    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    can_edit = not (is_chat_mode(mode) or is_plan_mode(mode))

    explore = _explore_hint(config)
    confirm_cmd = (
        _path_uncertainty_hint(
            explore,
            is_windows=is_windows,
            windows_with_bash=windows_with_bash,
            shell_is_powershell=shell_is_powershell,
        )
        + ' Prefer editors over shell directory guessing.'
    )
    if not is_windows or windows_with_bash:
        proc_find = 'Never `pkill -f` broadly — `ps`/`grep` then `kill <PID>`.'
    else:
        proc_find = (
            "Find: `Get-Process | Where-Object { $_.ProcessName -like '*name*' }`; "
            'kill: `Stop-Process -Id <PID>`.'
        )
    checkpoints = getattr(config, 'enable_checkpoints', False)
    checkpoint_rollback_hint = (
        '; use **checkpoint** for coarse rollback' if checkpoints else ''
    )

    if not can_edit:
        editor_ops = (
            '<EDITOR_AND_FILE_OPERATIONS>\n'
            f'Editor `path` values normalize safely. {confirm_cmd}\n'
            '**File API mental model**\n'
            '- Context: `read` for file, range, or symbol bodies.\n'
            '- Discovery: `find_symbols` returns candidates.\n'
            '</EDITOR_AND_FILE_OPERATIONS>'
        )
    else:
        editor_ops = (
            '<EDITOR_AND_FILE_OPERATIONS>\n'
            f'Editor `path` values normalize safely. {confirm_cmd}\n'
            'Edit the user path directly; no shadow copies; remove temp files when done.\n\n'
            '**File API mental model**\n'
            '- Discovery: `find_symbols` returns candidates.\n'
            '- Context: `read` for file, range, or symbol bodies. `read(type="symbols")` returns each target as resolved, ambiguous, or not_found.\n'
            '- Creation: `create(type="file")` for new files; `create(type="symbol")` for new symbols anchored to existing code.\n'
            '- Code: `edit_symbols` for modifying/deleting existing symbols; prefer `path` + `qualified_name` + `symbol_kind` for write targets.\n'
            '- Text/config/docs: `replace_string`; add by anchor -> anchor + content, delete with `new_string=""`.\n'
            '- Refactor atomically across files: `multiedit`.\n'
            '- Never write source via shell. Use real newlines/quotes, not serialized JSON strings.\n\n'
            '**Examples**\n'
            '- Find candidates: `find_symbols(query="authenticate")`.\n'
            '- Read symbols: `read(type="symbols", symbols=[{"qualified_name": "authenticate_user"}, {"qualified_name": "UserService"}])`.\n'
            '- APPEND config: `replace_string(old_string="# END CONFIG", new_string="new_key=new_value\\n# END CONFIG")` — anchor to a unique line, then insert before it.\n'
            '- DELETE: `replace_string(old_string="old config block", new_string="")`.\n'
            '- Code/content payloads must represent normal source text. Do not include literal backslash-n sequences unless the target file actually requires them. Transport escaping is handled by the tool API; do not serialize code yourself.\n'
            '- Multiple functions: `edit_symbols`; implementation + tests: `multiedit`.\n'
            '</EDITOR_AND_FILE_OPERATIONS>'
        )


    return render_partial(
        'system_partial_02_tools.md',
        confirm_paths=confirm_cmd,
        process_management=proc_find,
        checkpoint_rollback_hint=checkpoint_rollback_hint,
        editor_and_file_operations=editor_ops,
    )


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
        '- **Calling `finish` with `task_tracker` items still `todo` or `doing`.** Sync the tracker first.'
        if tracker_on
        else ''
    )

    destructive_ops_antipattern = (
        '- **Running `rm`, `Remove-Item`, force pushes, or other destructive ops without explicit confirmation from the confirmation gate.**'
        + (' If available, take a `checkpoint` first.' if checkpoints_on else '')
        if True
        else ''
    )

    planning_tool_list = (
        '`task_tracker`, `{terminal_command_tool}`, and the public file API tools'
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


def _render_examples(
    render_partial: Callable[..., str],
    *,
    tracker_on: bool,
    meta_cognition_on: bool,
    lsp_available: bool,
    checkpoints_on: bool,
) -> str:
    """Render the worked-examples partial with capability-aware tool references."""
    if tracker_on:
        planning_hint = 'draft the plan with `task_tracker`'
    else:
        planning_hint = 'plan by thinking step-by-step in your head'

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
        'symbol lookup → `search_code`; `lsp` → `search_code`'
        if lsp_available
        else 'symbol lookup → `search_code`; refine the `search_code` query and read nearby files'
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
    if getattr(perm, 'shell_enabled', False) and getattr(
        perm, 'shell_allow_sudo', False
    ):
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
            'Follow **Configured MCP servers** above for *when* to prefer each server; '
            "match the user's task to those hints, then pick the concrete tool name from the list "
            "and each tool's description."
        )
    else:
        parts.append(
            "Infer *when* to call MCP from each tool's **name** and **description** in the list above "
            '(and avoid training-memory guesses for vendor-specific or version-specific facts—use a tool when one fits).'
        )
    parts.extend(
        (
            'Prefer **`call_mcp_tool`** over shell one-offs when an MCP tool covers the need. '
            'If asked what you can do or which models/tools you have, answer from **this** tool list, '
            '**MCP server hints** (if any), and your configured model id—**not** generic "no web / no docs" tropes.',
            'On failure, MCP results carry a `category` field. Use it to pick the next move: '
            '`bad_args` → fix arguments and retry once; '
            '`timeout` → narrow the scope and retry; '
            '`tool_bug` → switch to a different tool; '
            '`env` → fall back to a non-MCP tool (e.g. terminal); '
            '`not_found` → pick a tool name from the list above.',
            '</MCP_WHEN_TO_USE>',
        )
    )


def _mcp_tail_render_kwargs(
    render_partial: Callable[..., str],
    config: Any,
) -> str:
    meta_cognition = getattr(config, 'enable_meta_cognition', False)
    communicate_tool_section = (
        '<COMMUNICATE_TOOL>\n'
        'Use `communicate_with_user` for clarification, uncertainty, risky-action options, or escalation after 3 failed attempts on a sub-task. On escalation, include a brief post-mortem and one specific question. Do not ask mid-task questions in plain text; use this tool so the turn ends cleanly and waits for user input.\n'
        '</COMMUNICATE_TOOL>'
        if meta_cognition
        else ''
    )
    lsp_available = _lsp_available(config)
    if lsp_available:
        uncertainty_state_1_discover_line = '**Can be discovered** (unknown path, API, or config shape) → follow **TOOL_ROUTING_LADDER**; use tools like `search_code`, editor `view_*`, or `lsp`. Do NOT ask first.'
    else:
        uncertainty_state_1_discover_line = '**Can be discovered** (unknown path, API, or config shape) → follow **TOOL_ROUTING_LADDER**, not shell repo search/read. Do NOT ask first.'
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
