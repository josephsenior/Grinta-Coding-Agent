"""System capabilities block: runtime-truth statements for the agent.

This block exists so the agent can never lie about its own runtime behavior.
Every bullet is derived from a live config flag or runtime check — do NOT
add aspirational text here. If you change a default, this block updates
automatically on the next prompt assembly.
"""

from __future__ import annotations

from typing import Any

from backend.core.constants import (
    DEFAULT_AGENT_DEBUGGER_ENABLED,
    DEFAULT_AGENT_LSP_QUERY_ENABLED,
)
from backend.engine.prompts.section_renderers._common import _semantic_recall_runtime


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


def _lsp_language_server_labels() -> list[str]:
    """Return ``language → server`` labels matching the TUI LSP sidebar.

    Iterates ``CANONICAL_LSP_SERVERS`` (one server per language) and
    cross-references availability by server name — so the label always
    matches the server that actually launches.
    """
    from backend.utils.runtime_detect import CANONICAL_LSP_SERVERS, detect_lsp_servers

    detected = detect_lsp_servers()
    labels: list[str] = []
    for key, spec in sorted(CANONICAL_LSP_SERVERS.items()):
        tool = detected.get(spec.name)
        if tool is None or not tool.available:
            continue
        labels.append(f'{key} → {spec.name}')
    return labels


def _render_runtime_detection_lines(config: Any) -> tuple[str, str]:
    r"""Return ``(lsp_line, dap_line)`` summarizing detected runtimes.

    When ``enable_lsp_query`` / ``enable_debugger`` is false, returns ``''`` for that
    line so the capability block omits the tool entirely (no \"DISABLED\" bullet).
    """
    lsp_enabled = bool(
        getattr(config, 'enable_lsp_query', DEFAULT_AGENT_LSP_QUERY_ENABLED)
    )
    debugger_enabled = bool(
        getattr(config, 'enable_debugger', DEFAULT_AGENT_DEBUGGER_ENABLED)
    )
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

    lsp_entries = _lsp_language_server_labels() if any_lsp else []
    if not lsp_enabled:
        lsp_line = ''
    elif lsp_entries:
        lsp_line = (
            '- **Language servers (LSP / `lsp`)**: detected → '
            f'{"; ".join(lsp_entries)}. Use `lsp` for definition / '
            'references / hover / diagnostics on those languages. '
            'For file edits use the public file API tools; `lsp` is read-only. For file reads use `read_file`.'
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
    semantic_recall_active: bool | None = None,
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
        if _semantic_recall_runtime(
            config, semantic_recall_active=semantic_recall_active
        )
        else 'working / episodic'
    )
    criteria_on = bool(getattr(config, 'enable_acceptance_criteria_tool', True))
    tracker_on = bool(getattr(config, 'enable_task_tracker_tool', True))
    persisted_surfaces: list[str] = []
    if criteria_on:
        persisted_surfaces.append('acceptance criteria')
    if tracker_on:
        persisted_surfaces.append('task plans')
    if persisted_surfaces:
        survival_list = (
            'verified facts, '
            + ', '.join(persisted_surfaces)
            + ', and the immediate task surface'
        )
    else:
        survival_list = 'verified facts and the immediate task surface'
    condensation_line = (
        '- **Conversation condensation**: AUTOMATIC and middleware-driven. '
        'It costs ZERO tool calls and ZERO turns from your budget. '
        f'It uses a {condensation_tiers} memory model and re-injects a pre-condensation '
        f'snapshot after pruning, so {survival_list} survive. '
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
    if _semantic_recall_runtime(config, semantic_recall_active=semantic_recall_active):
        memory_line = (
            '- **Search History (`search_history`)**: search earlier conversation and tool-event history when required '
            'information is no longer visible.'
        )

    checkpoint_line = ''
    if bool(getattr(config, 'enable_checkpoints', True)) and can_edit:
        checkpoint_line = (
            '- **Checkpoints (`checkpoint`)**: risky edits/commands get automatic pre-action snapshots '
            '(rollback middleware). Use `checkpoint(save)` for named phase milestones, '
            '`checkpoint(view)` to list checkpoints, `checkpoint(revert)` after a bad edit or failed command, '
            '`checkpoint(clear)` when the milestone list is stale or a fresh phase starts. '
            'Prefer `undo_last_edit` for the last file write.'
        )

    # External MCP tool catalogue status — single source of truth for
    # the model so it never has to guess whether MCP tools exist. When
    # the catalogue is empty we say so explicitly, which is the only
    # way to prevent the model from hallucinating tool names.
    mcp_status_line = _render_mcp_status_line(config)

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
    if mcp_status_line:
        parts.append(f'{mcp_status_line}\n')
    if browser_line:
        parts.append(f'{browser_line}\n')
    if memory_line:
        parts.append(f'{memory_line}\n')
    if checkpoint_line:
        parts.append(f'{checkpoint_line}\n')
    if detection_block:
        parts.append(detection_block)

    return '\n'.join(parts)


def _render_mcp_status_line(config: Any) -> str:
    """Render the ``External MCP tools`` bullet.

    Reads :data:`get_mcp_bootstrap_status` (set by
    :func:`add_mcp_tools_to_agent`) so the prompt always reflects
    what is actually wired up — never what the operator *wished* was
    wired up. Empty state is explicit so the model does not invent
    tool names when the catalogue is empty.
    """
    mcp_status: dict[str, Any] = {}
    bootstrap = getattr(config, 'mcp_capability_status', None)
    if isinstance(bootstrap, dict):
        mcp_status = bootstrap
    else:
        try:
            from backend.integrations.mcp.mcp_bootstrap_status import (
                get_mcp_bootstrap_status,
            )

            mcp_status = get_mcp_bootstrap_status() or {}
        except Exception:
            mcp_status = {}

    state = str(mcp_status.get('state') or 'unknown')
    remote_tool_count = int(mcp_status.get('remote_tool_param_count') or 0)
    connected_clients = int(mcp_status.get('connected_client_count') or 0)
    last_error = mcp_status.get('last_error')

    if remote_tool_count > 0 and connected_clients > 0:
        return (
            f'- **External MCP tools**: {remote_tool_count} tool'
            f'{"s" if remote_tool_count != 1 else ""} from '
            f'{connected_clients} connected server'
            f'{"s" if connected_clients != 1 else ""}. See the per-turn '
            '`<MCP_TOOLS>` section for the names; route calls through '
            '`call_mcp_tool(tool_name=..., arguments={...})`.'
        )
    if state == 'mcp_disabled':
        return (
            '- **External MCP tools**: disabled (`mcp_config.enabled=false` in '
            '`settings.json`). Enable in **Settings → MCP Servers** to '
            'route calls through `call_mcp_tool`.'
        )
    if state == 'no_servers_configured':
        return (
            '- **External MCP tools**: none configured. Add a server in '
            '**Settings → MCP Servers**; connected tools appear under the '
            'per-turn `<MCP_TOOLS>` section.'
        )
    if state in ('no_clients_connected', 'fetch_failed') and last_error:
        return (
            f'- **External MCP tools**: none reachable ({last_error}). '
            'Check **Settings → MCP Servers** or set `APP_MCP_DEBUG=1` for '
            'connection logs.'
        )
    if state in ('no_clients_connected', 'fetch_failed'):
        return (
            '- **External MCP tools**: none reachable. Check '
            '**Settings → MCP Servers** for connection state.'
        )
    # Unknown / healthy-but-empty: same canonical message. The model
    # needs ONE stable answer for "is MCP working?" — not a per-state
    # essay.
    return (
        '- **External MCP tools**: none connected. Configure servers in '
        '**Settings → MCP Servers**; tools appear under the per-turn '
        '`<MCP_TOOLS>` section once a server is enabled and reachable.'
    )
