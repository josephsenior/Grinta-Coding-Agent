"""System capabilities block: runtime-truth statements for the agent.

This block exists so the agent can never lie about its own runtime behavior.
Every bullet is derived from a live config flag or runtime check — do NOT
add aspirational text here. If you change a default, this block updates
automatically on the next prompt assembly.
"""

from __future__ import annotations

from typing import Any


def _vector_memory_runtime(config: Any) -> bool:
    from backend.utils.optional_extras import vector_memory_enabled

    return vector_memory_enabled(config)


def _browser_runtime(config: Any) -> bool:
    from backend.utils.optional_extras import browser_tool_enabled

    return browser_tool_enabled(config)


def _render_parallel_scheduling_line(
    config: Any,
    *,
    parallel_tool_calls_provider_flag: bool,
) -> str:
    """One-line parallel tool_calls hint when the runtime supports it; else omit."""
    parallel_enabled = bool(getattr(config, 'enable_parallel_tool_scheduling', False))
    if not (parallel_enabled and parallel_tool_calls_provider_flag):
        return ''
    return (
        '- **Parallel tool calls**: supported — emit multiple independent tool_calls '
        'in one assistant message when that improves latency.'
    )


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
                '- **Debug adapters (DAP / `debugger`)**: usable adapters detected → '
                f'{", ".join(debug_available)}. The `debugger` tool resolves the right '
                'adapter automatically from the file extension or `adapter` field; do not '
                'pass `adapter_command` unless you have a custom stdio or DAP-over-TCP '
                'adapter binary.'
            )
        else:
            dap_line = ''
    return lsp_line, dap_line


def _render_system_capabilities(
    config: Any,
    *,
    function_calling_mode: str | None,
    parallel_tool_calls_provider_flag: bool,
    mode: str = 'agent',
) -> str:
    """Runtime-truth capability statement.

    This block exists so the agent can never lie about its own runtime behavior.
    Every bullet is derived from a live config flag or runtime check — do NOT
    add aspirational text here. If you change a default, this block updates
    automatically on the next prompt assembly.
    """
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
    )

    can_edit = not (is_chat_mode(mode) or is_plan_mode(mode))

    parallel_line = _render_parallel_scheduling_line(
        config,
        parallel_tool_calls_provider_flag=parallel_tool_calls_provider_flag,
    )

    condensation_tiers = (
        'working / episodic / semantic'
        if _vector_memory_runtime(config)
        else 'working / episodic'
    )
    condensation_line = (
        '- **Conversation condensation**: AUTOMATIC and middleware-driven. '
        'It costs ZERO tool calls and ZERO turns from your budget. '
        f'It uses a {condensation_tiers} memory model and re-injects a pre-condensation '
        'snapshot after pruning, so verified facts and the immediate task surface survive. '
        'Do not describe condensation as "lossy" or as something you must invoke manually.'
    )

    web_line = ''
    if bool(getattr(config, 'enable_web', True)):
        web_line = (
            '- **Web (`web_search` / `web_fetch`)**: native tools backed by bundled Exa MCP '
            '(search + markdown fetch). `EXA_API_KEY` is optional — preferred for higher limits, '
            'not required. `web_fetch` falls back to fetch MCP when Exa cannot read a URL.'
        )

    docs_line = ''
    if bool(getattr(config, 'enable_docs', True)):
        docs_line = (
            '- **Library docs (`docs_resolve` / `docs_query`)**: native tools backed by bundled '
            'Context7 MCP for current framework/SDK documentation. `CONTEXT7_API_KEY` is optional '
            '— preferred for higher limits, not required. Call `docs_resolve` first unless you '
            'already have a `/org/project` corpus ID.'
        )

    browser_line = ''
    if _browser_runtime(config) and can_edit:
        web_fetch_hint = (
            'Use `web_fetch` for static URLs; `browser` when interaction is required.'
            if bool(getattr(config, 'enable_web', True))
            else 'Use when pages need interaction (forms, logins, JS SPAs).'
        )
        browser_line = (
            '- **Browser (`browser`)**: in-process Chromium for interactive pages — forms, '
            f'logins, JS SPAs. {web_fetch_hint}'
        )

    memory_line = ''
    if bool(getattr(config, 'enable_working_memory', True)) and can_edit:
        recall_hint = (
            ', `recall` for semantic search over indexed history'
            if _vector_memory_runtime(config)
            else ''
        )
        memory_line = (
            '- **Memory (`memory`)**: `working` for session reasoning, `persist` for rare workspace '
            f'facts{recall_hint}. Task progress belongs in `task_tracker`, not memory.'
        )

    checkpoint_line = ''
    if bool(getattr(config, 'enable_checkpoints', False)) and can_edit:
        checkpoint_line = (
            '- **Checkpoints (`checkpoint`)**: risky edits/commands get automatic pre-action snapshots '
            '(rollback middleware). Use `save` for named phase milestones, `view` to list checkpoints, '
            '`revert` after a bad edit or failed command, `clear` when the milestone list is stale or '
            'a fresh phase starts. Prefer `undo_last_edit` for the last file write.'
        )

    # Runtime-detected language servers / debug adapters — only when those tools
    # are enabled in config (omit bullets entirely when gated off).
    lsp_line, dap_line = _render_runtime_detection_lines(config)
    if not can_edit:
        dap_line = ''  # debugger not available in Chat/Plan
    detection_block = '\n'.join(line for line in (lsp_line, dap_line) if line)
    runtime_discovery_hint = (
        '\nIn particular, **never run shell commands like `Get-Command`/`which`/`where` '
        'to discover language servers or debug adapters** — the bullets in this section '
        'for those tools are the authoritative answer.'
        if detection_block
        else ''
    )

    parts = [
        '# 🧠 System Capabilities (verified at runtime)\n'
        'The following statements are derived from live config and feature flags. '
        'Treat them as authoritative — do not contradict them in user-facing replies.'
        f'{runtime_discovery_hint}\n\n'
        f'{condensation_line}\n'
    ]
    if parallel_line:
        parts.append(f'{parallel_line}\n')
    if web_line:
        parts.append(f'{web_line}\n')
    if docs_line:
        parts.append(f'{docs_line}\n')
    if browser_line:
        parts.append(f'{browser_line}\n')
    if memory_line:
        parts.append(f'{memory_line}\n')
    if checkpoint_line:
        parts.append(f'{checkpoint_line}\n')
    if detection_block:
        parts.append(detection_block)

    return '\n'.join(parts)
