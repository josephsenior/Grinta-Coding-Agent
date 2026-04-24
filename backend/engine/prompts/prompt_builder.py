"""Pure-Python prompt builder — replaces Jinja2 template rendering.

Each template partial is a function that returns a string.  Static
sections are loaded from .md files on disk; dynamic sections are
assembled via f-strings and simple loops.

Public API
----------
build_system_prompt(**ctx)   → full system prompt string
measure_system_prompt_sections(**ctx) → token/char breakdown (for budgeting; run ``python -m backend.engine.prompts.prompt_builder``)
build_workspace_context(...) → additional_info block
build_playbook_info(...)     → playbook block
build_knowledge_base_info(.) → knowledge-base block
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.utils.prompt import (
        ConversationInstructions,
        RepositoryInfo,
        RuntimeInfo,
    )

_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_section_tokens(text: str, model_id: str) -> tuple[int, str]:
    """Best-effort token count for budgeting. Returns (tokens, encoding_label).

    Model-family awareness:
    - Known tiktoken models: resolved directly via ``encoding_for_model``.
    - Claude (claude-*): uses o200k_base + 1.05x correction factor (Claude's
      tokenizer encodes ~5% more tokens than GPT-4o on typical code/text).
    - Gemini (gemini-*): uses o200k_base (similar vocabulary to GPT-4o).
    - All others: falls back to o200k_base (safer than cl100k_base for modern models).
    """
    try:
        import tiktoken  # type: ignore

        mid = (model_id or "").strip().lower()

        # Try exact match first (covers all GPT / o1 / o3 variants)
        if mid:
            try:
                enc = tiktoken.encoding_for_model(mid)
                tokens = len(enc.encode(text))
                return tokens, f"model:{mid}"
            except Exception:
                pass

        # Model-family fallback
        enc = tiktoken.get_encoding("o200k_base")
        tokens = len(enc.encode(text))

        if mid.startswith("claude-"):
            # Claude tokenizer produces ~5% more tokens on average
            tokens = int(tokens * 1.05)
            return tokens, "o200k_base+claude_correction"

        label = "o200k_base" if mid else "o200k_base_default"
        return tokens, label
    except Exception:
        est = max(0, len(text) // 4)
        return est, "chars_div_4_fallback"


@lru_cache(maxsize=32)
def _load(name: str) -> str:
    """Read a .md partial from the prompts directory and cache it."""
    return (_DIR / name).read_text(encoding="utf-8").strip()


def _choose(is_windows: bool, win: str, unix: str) -> str:
    return win if is_windows else unix


def _resolve_terminal_command_tool(
    is_windows: bool,
    terminal_tool_name: str | None,
) -> str:
    """Resolve the active terminal command tool for prompt rendering."""
    if terminal_tool_name:
        return terminal_tool_name
    return "execute_powershell" if is_windows else "execute_bash"


def _code_intelligence_available(config: Any = None) -> bool:
    """Return whether the code_intelligence tool should be considered available."""
    if not getattr(config, "enable_lsp_query", False):
        return False
    try:
        from backend.utils.lsp_client import _detect_pylsp

        return bool(_detect_pylsp())
    except Exception:
        return False


def _explore_hint(_config: Any = None) -> str:
    """Return the canonical layout-discovery tool hint."""
    return (
        "`search_code` first, then `explore_tree_structure`; "
        "use `analyze_project_structure` only when needed"
    )


# ---------------------------------------------------------------------------
# system_partial_00_routing
# ---------------------------------------------------------------------------


def _render_routing(
    is_windows: bool,
    config: Any = None,
    function_calling_mode: str | None = None,
) -> str:
    explore = _explore_hint(config)
    code_intelligence_available = _code_intelligence_available(config)
    meta_cognition_on = getattr(config, "enable_meta_cognition", False)
    working_memory_on = getattr(config, "enable_working_memory", True)
    condensation_on = getattr(config, "enable_condensation_request", False)
    tracker_on = getattr(config, "enable_internal_task_tracker", False)
    batch_cmds = _choose(
        is_windows,
        f"Use **PowerShell** only for environment actions (install, build, test, git, processes). "
        f"For repo layout and file content, use **{explore}** "
        "and **`str_replace_editor` (`view_file`)**—not `Get-Content`/`Select-String` pipelines for source trees.",
        f"Use **bash** only for environment actions (install, build, test, git, processes). "
        f"For repo layout and file content, use **{explore}** "
        "and **`str_replace_editor` (`view_file`)**—not `ls && cat && grep` chains for project files.",
    )
    code_intelligence_routing = (
        "- **Known file + symbol position, precise definition/references/hover** → `code_intelligence`"
        if code_intelligence_available
        else ""
    )
    mode = (function_calling_mode or "unknown").strip().lower()
    if mode == "native":
        tool_call_batching_mode = (
            "Native function-calling mode is active. You may batch independent tool calls "
            "in one assistant turn when it improves latency; keep dependent calls sequential."
        )
    elif mode == "string":
        tool_call_batching_mode = (
            "Fallback string-parsing mode is active. Emit exactly one tool call per assistant "
            "message and continue step-by-step."
        )
    else:
        tool_call_batching_mode = (
            "Mode is unknown. Use conservative single tool-call turns unless runtime capability "
            "signals explicitly confirm native multi-call support."
        )
    ambiguous_intent_instruction = (
        "Use `communicate_with_user` to offer options rather than guessing."
        if meta_cognition_on
        else "Ask the user a short clarifying question in natural language rather than guessing."
    )
    if working_memory_on:
        memory_and_context_section = (
            "<MEMORY_AND_CONTEXT_TOOLS>\n"
            "- Disk facts: `note(key, value)` / `recall(key)`.\n"
            "- Session state: `memory_manager(action=\"working_memory\", ...)` and `memory_manager(action=\"semantic_recall\", key=...)`.\n"
            "Rule: long-lived facts → `note`; task-local state → `memory_manager`.\n"
            "</MEMORY_AND_CONTEXT_TOOLS>"
        )
        post_condensation_retrieval = (
            "Call `memory_manager(action=\"working_memory\")` after condensation to restore plan/findings before acting."
        )
        surviving_state_facts = (
            "Only `note` (disk) and `memory_manager` (session) facts reliably survive condensation."
        )
    else:
        memory_and_context_section = (
            "<MEMORY_AND_CONTEXT_TOOLS>\n"
            "- Disk facts still use `note(key, value)` / `recall(key)`.\n"
            "- No structured within-session working-memory tool is available in this run; keep active hypotheses compact and rely on verified observations.\n"
            "</MEMORY_AND_CONTEXT_TOOLS>"
        )
        post_condensation_retrieval = (
            "Resume from the summary and your most recent verified observations; no structured working-memory tool is available in this run."
        )
        surviving_state_facts = (
            "Only `note` (disk) facts are guaranteed to survive condensation."
        )
    context_budget_sync_clause = ", sync `task_tracker`" if tracker_on else ""
    context_budget_next_step = (
        "call `finish` or `summarize_context`"
        if condensation_on
        else "call `finish` or close the current sub-task before doing any broader exploration"
    )
    repetition_recovery_options = (
        "switch tools, escalate with `communicate_with_user`, or call `finish` with a partial result."
        if meta_cognition_on
        else "switch tools, ask the user a short clarifying question, or call `finish` with a partial result."
    )
    remaining_work_source_of_truth = (
        "Trust your `task_tracker` plan as the source of truth for what remains."
        if tracker_on
        else "Use restored working memory and recent verified observations as the source of truth for what remains."
    )
    return _load("system_partial_00_routing.md").format(
        ambiguous_intent_instruction=ambiguous_intent_instruction,
        batch_commands=batch_cmds,
        code_intelligence_routing=code_intelligence_routing,
        context_budget_sync_clause=context_budget_sync_clause,
        context_budget_next_step=context_budget_next_step,
        explore_layout_hint=explore,
        memory_and_context_section=memory_and_context_section,
        post_condensation_retrieval=post_condensation_retrieval,
        remaining_work_source_of_truth=remaining_work_source_of_truth,
        repetition_recovery_options=repetition_recovery_options,
        surviving_state_facts=surviving_state_facts,
        tool_call_batching_mode=tool_call_batching_mode,
    )


# ---------------------------------------------------------------------------
# security_risk_assessment
# ---------------------------------------------------------------------------


def _render_security(cli_mode: bool = True) -> str:
    risk_block = (
        "- **LOW**: Safe, read-only actions.\n"
        "  - Viewing/summarizing content, reading project files, simple in-memory calculations.\n"
        "- **MEDIUM**: Project-scoped edits or execution.\n"
        "  - Modify user project files, run project scripts/tests, install project-local packages.\n"
        "- **HIGH**: System-level or untrusted operations.\n"
        "  - Changing system settings, global installs, elevated (`sudo`) commands, deleting critical files, "
        "downloading & executing untrusted code, or sending local secrets/data out."
    )
    return (
        "# 🔐 Security Risk Policy\n"
        "When using tools that support the security_risk parameter, assess the safety risk of your actions:\n\n"
        f"{risk_block}\n\n"
        "**Global Rules**\n"
        "- Always escalate to **HIGH** if sensitive data leaves the environment."
    )


# ---------------------------------------------------------------------------
# system_partial_01_autonomy_execution
# ---------------------------------------------------------------------------


def _render_autonomy(config: Any, is_windows: bool) -> str:
    level = getattr(config, "autonomy_level", "balanced")
    checkpoints = getattr(config, "enable_checkpoints", False)
    code_intelligence_available = _code_intelligence_available(config)
    cp_line = (
        " Auto-save occurs before large writes; use 'checkpoint' tool to manually save logically safe states."
        if checkpoints
        else ""
    )

    autonomy = ""
    if level == "full":
        autonomy = (
            f"<AUTONOMY>\nFULL AUTONOMOUS MODE: Execute all planned steps end-to-end without "
            f"confirmation. On tool failure, pivot to alternative tools immediately within the "
            f"same turn (e.g. ast_code_editor → str_replace_editor). Auto-retry "
            f"recoverable errors. Report back only after completing the full plan or after "
            f"exhausting all tool alternatives on a blocking sub-task. "
            f"{cp_line}\n</AUTONOMY>"
        )

    path_hint = _choose(
        is_windows,
        f"run {_explore_hint(config)}, or list with `Get-ChildItem` only if no tool fits",
        f"run {_explore_hint(config)}—avoid blind `cat` of guessed paths",
    )
    code_intelligence_fallback = (
        "- `search_code` returns nothing → try `code_intelligence`"
        if code_intelligence_available
        else "- `search_code` returns nothing → try alternate search terms, do not fall back to shell."
    )
    tracker_on = getattr(config, "enable_internal_task_tracker", False)
    signal_on = getattr(config, "enable_signal_progress", False)
    if tracker_on:
        signal_blurb = ""
        if signal_on:
            signal_blurb = (
                "\n\n**signal_progress** is enabled: use it per its tool description for deferral / "
                "heartbeat-style notes when appropriate. It does not replace accurate `task_tracker` state."
            )
        task_tracker_discipline_block = (
            "<TASK_TRACKING>\n"
            "**task_tracker**: For multi-step tasks, use `view` to read the plan and `update` to replace the full `task_list`.\n"
            "Allowed statuses: `todo`, `doing`, `done`, `skipped`, `blocked`.\n"
            "**Syncing**: Update the tracker immediately when step statuses change. Piggyback updates with other tool calls when possible.\n"
            "**Completion (CRITICAL)**: You MUST NOT call the finish tool if any steps are still in `todo` or `doing`."
            f"{signal_blurb}\n"
            "</TASK_TRACKING>"
        )
    else:
        task_tracker_discipline_block = ""

    base_workflow = (
        "Default loop: scope → reproduce → isolate → fix → verify.\n"
        "For debug/fix tasks, re-run the same reproducer when possible."
    )
    if tracker_on:
        problem_solving_workflow_body = (
            base_workflow
            + "\n\nWith **task_tracker** enabled, treat **sync** as part of the loop: after verify, update "
            "the plan when your beliefs about progress changed."
        )
        task_sync_instruction = (
            "**Task synchronization:** Update `task_tracker` to `done`, `skipped`, or `blocked` before attempting to finish."
        )
    else:
        problem_solving_workflow_body = base_workflow
        task_sync_instruction = (
            "**Plan synchronization:** Keep your working memory and finish summary aligned with what was actually completed before attempting to finish."
        )

    return _load("system_partial_01_autonomy.md").format(
        autonomy_block=autonomy,
        task_tracker_discipline_block=task_tracker_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        code_intelligence_fallback=code_intelligence_fallback,
        problem_solving_workflow_body=problem_solving_workflow_body,
    )


# ---------------------------------------------------------------------------
# system_partial_02_tool_reference
# ---------------------------------------------------------------------------


def _render_tool_reference(is_windows: bool, config: Any = None) -> str:
    explore = _explore_hint(config)
    confirm_cmd = _choose(
        is_windows,
        f"If unsure where a file lives, use {explore} before opening it—not only `Get-ChildItem`.",
        f"If unsure where a file lives, use {explore} before opening it—not only `ls`.",
    )
    proc_find = _choose(
        is_windows,
        "Find: `Get-Process | Where-Object { $_.ProcessName -like '*name*' }`; kill: `Stop-Process -Id <PID>`.",
        "Never `pkill -f` broadly — `ps`/`grep` then `kill <PID>`.",
    )
    checkpoints = getattr(config, "enable_checkpoints", False)
    checkpoint_rollback_hint = (
        "; use **checkpoint** / **revert_to_checkpoint** for coarse rollback"
        if checkpoints
        else ""
    )
    return _load("system_partial_02_tools.md").format(
        confirm_paths=confirm_cmd,
        process_management=proc_find,
        checkpoint_rollback_hint=checkpoint_rollback_hint,
    )


def _render_critical(
    terminal_command_tool: str,
    *,
    enable_think: bool,
    terminal_manager_available: bool,
) -> str:
    """Render last-mile critical execution rules with dynamic terminal tool naming."""
    think_execution_rule = (
        "**`think` does not execute** — after reasoning, you must still call tools."
        if enable_think
        else "**Reasoning alone does not execute** — after reasoning, you must still call tools."
    )
    if terminal_manager_available:
        terminal_manager_rule = (
            "**Interactive terminal discipline**:\n"
            "   - For `terminal_manager action=open`, reuse only the returned `session_id`; never invent one. The `open` command already runs; later commands use `action=input`.\n"
            "   - Prefer `action=read` with `mode=delta`; reuse `next_offset` or omit `offset`.\n"
            "   - If output stalls, stop repeating the same `read` / `input` / `control`; send a different command or pivot tools.\n"
            "   - Read an opened session before opening another similar one.\n"
            "   - If the latest user message is about your behavior rather than more terminal work, answer in natural language first."
        )
    else:
        terminal_manager_rule = (
            f"**Interactive terminal sessions are unavailable in this run** — do not refer to `terminal_manager`; use `{terminal_command_tool}` for non-interactive command execution only."
        )
    return _load("system_partial_04_critical.md").format(
        terminal_command_tool=terminal_command_tool,
        terminal_manager_rule=terminal_manager_rule,
        think_execution_rule=think_execution_rule,
    )


# ---------------------------------------------------------------------------
# system_partial_03_mcp_permissions_tail  (most complex)
# ---------------------------------------------------------------------------


def _render_mcp_and_permissions(
    mcp_tool_names: list[str],
    mcp_tool_descriptions: dict[str, str],
    mcp_server_hints: list[dict[str, str]],
    config: Any,
) -> str:
    parts: list[str] = ["<MCP_TOOLS>"]

    if mcp_tool_names:
        total = len(mcp_tool_names)

        parts.append(
            f'🔌 **External MCP tools** ({total}): use **`call_mcp_tool(tool_name="...", arguments={{...}})`** '
            f"— argument shapes match the registered tool schema."
        )
        parts.append(
            "**Tool-name discipline (critical):** Pass each tool name to "
            "`call_mcp_tool(tool_name=...)` **exactly as listed below** — the names "
            "are already flat. Do **not** add `server:`, `server/`, `server.`, "
            "`server__` or any other prefix; those are not part of the name and "
            "will fail. If a name you want is not in this list, that tool is "
            "not available in this session — pick a different tool or an "
            "alternative approach. Do not guess."
        )
        for name in mcp_tool_names:
            parts.append(f"- `{name}`: {mcp_tool_descriptions[name]}")

        if mcp_server_hints:
            parts.append("")
            parts.append("<MCP_SERVER_HINTS>")
            parts.append(
                "**Configured MCP servers (when to use each — from your MCP settings):**"
            )
            for row in mcp_server_hints:
                parts.append(f'- **`{row["server"]}`:** {row["hint"]}')
            parts.append("</MCP_SERVER_HINTS>")

        parts.append("")
        parts.append("<MCP_WHEN_TO_USE>")
        parts.append("**Discipline (MCP):**")
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
        parts.append(
            "Prefer **`call_mcp_tool`** over shell one-offs when an MCP tool covers the need. "
            "If asked what you can do or which models/tools you have, answer from **this** tool list, "
            '**MCP server hints** (if any), and your configured model id—**not** generic "no web / no docs" tropes.'
        )
        parts.append("</MCP_WHEN_TO_USE>")
    else:
        parts.append("No external MCP tools connected.")
    parts.append("</MCP_TOOLS>")

    # Permissions
    if getattr(config, "enable_permissions", False):
        perm = getattr(config, "permissions", None)
        if perm is not None:
            parts.append("")
            parts.append(_render_permissions(config, perm))

    # Static tail sections
    meta_cognition = getattr(config, "enable_meta_cognition", False)
    enable_think = bool(getattr(config, "enable_think", False))
    communicate_tool_section = (
        "<COMMUNICATE_TOOL>\n"
        "Use `communicate_with_user` for clarification, uncertainty, risky-action options, or escalation after 3 failed attempts on a sub-task. On escalation, include a brief post-mortem and one specific question. Do not ask mid-task questions in plain text; use this tool so the turn ends cleanly and waits for user input.\n"
        "</COMMUNICATE_TOOL>"
        if meta_cognition
        else ""
    )
    code_intelligence_available = _code_intelligence_available(config)
    if code_intelligence_available:
        uncertainty_state_1_discover_line = (
            "**Can be discovered** (unknown path, API, or config shape) → follow **TOOL_ROUTING_LADDER**; use tools like `search_code`, editor `view_*`, or `code_intelligence`. Do NOT ask first."
        )
    else:
        uncertainty_state_1_discover_line = (
            "**Can be discovered** (unknown path, API, or config shape) → follow **TOOL_ROUTING_LADDER**, not shell repo search/read. Do NOT ask first."
        )
    parts.append("")
    thinking_tool_section = (
        "<THINKING_TOOL>\n"
        "Use `think` for multi-step planning, complex debugging, or architecture trade-offs. It records reasoning only; it does not execute actions.\n"
        "</THINKING_TOOL>"
        if enable_think
        else ""
    )
    parts.append(
        _load("system_partial_03_tail.md").format(
            communicate_tool_section=communicate_tool_section,
            interaction_guidance=(
                "If a request is vague, inspect nearby docs/config first; use `communicate_with_user` only if you are still blocked or the scope is still ambiguous."
                if meta_cognition
                else "If a request is vague, inspect nearby docs/config first; ask the user directly in natural language only if you are still blocked or the scope is still ambiguous."
            ),
            uncertainty_state_1_discover_line=uncertainty_state_1_discover_line,
            uncertainty_state_2_ambiguous_line=(
                "**Ambiguous intent** (multiple valid implementations, destructive action, unclear scope) → `communicate_with_user` with `options`. Do NOT guess."
                if meta_cognition
                else "**Ambiguous intent** (multiple valid implementations, destructive action, unclear scope) → ask the user a short clarifying question in natural language. Do NOT guess."
            ),
            uncertainty_state_3_unknowable_line=(
                "**Needs user input** (user preference, external credential, business policy) → `communicate_with_user` with `intent='clarification'`."
                if meta_cognition
                else "**Needs user input** (user preference, external credential, business policy) → ask the user directly in natural language."
            ),
            thinking_tool_section=thinking_tool_section,
        )
    )

    return "\n".join(parts)


def _render_permissions(config: Any, perm: Any) -> str:
    """Render the <PERMISSIONS> block from config.permissions."""
    file_w = "WRITE" if getattr(perm, "file_write_enabled", False) else "READ-ONLY"
    if getattr(perm, "file_write_enabled", False):
        file_w += f' (max {getattr(perm, "file_operations_max_size_mb", "?")}MB)'
    file_d = "DELETE" if getattr(perm, "file_delete_enabled", False) else "NO DELETE"
    blocked = ", ".join(getattr(perm, "file_operations_blocked_paths", []))

    git_parts: list[str] = []
    if getattr(perm, "git_enabled", False):
        if getattr(perm, "git_allow_commit", False):
            git_parts.append("COMMIT")
        if getattr(perm, "git_allow_push", False):
            git_parts.append("PUSH")
        if getattr(perm, "git_allow_force_push", False):
            git_parts.append("FORCE")
        if getattr(perm, "git_allow_branch_delete", False):
            git_parts.append("DELETE-BRANCH")
        git_str = " ".join(git_parts) or "ENABLED"
    else:
        git_str = "DISABLED"
    git_protected = ", ".join(getattr(perm, "git_protected_branches", []))

    shell_str = "ENABLED" if getattr(perm, "shell_enabled", False) else "DISABLED"
    if getattr(perm, "shell_enabled", False) and getattr(
        perm, "shell_allow_sudo", False
    ):
        shell_str += " + SUDO"
    shell_blocked = ", ".join(getattr(perm, "shell_blocked_commands", []))

    net_str = "DISABLED"
    if getattr(perm, "network_enabled", False):
        net_str = f'{getattr(perm, "network_max_requests_per_minute", "?")}/min'
        domains = getattr(perm, "network_allowed_domains", [])
        if domains:
            net_str += f' | Only: {", ".join(domains)}'

    max_writes = getattr(perm, "max_file_writes_per_task", "?")
    max_cmds = getattr(perm, "max_shell_commands_per_task", "?")
    cost = getattr(perm, "max_cost_per_task", None)
    limits = f"{max_writes} files, {max_cmds} commands"
    if cost:
        limits += f", ${cost} cost"

    return (
        "<PERMISSIONS>\n"
        f"**File:** {file_w} | {file_d}\n"
        f"Blocked: {blocked}\n\n"
        f"**Git:** {git_str}\n"
        f"Protected: {git_protected}\n\n"
        f"**Shell:** {shell_str}\n"
        f"Blocked: {shell_blocked}\n\n"
        f"**Network:** {net_str}\n\n"
        f"**Limits:** {limits}/task\n\n"
        "Exceeding permissions → Error. Work within limits or request permission.\n"
        "</PERMISSIONS>"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _collect_system_prompt_sections(
    *,
    active_llm_model: str = "",
    is_windows: bool = False,
    windows_with_bash: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    terminal_tool_name: str | None = None,
    function_calling_mode: str | None = None,
    agent_identity: str = "",
) -> list[tuple[str, str]]:
    """Ordered (name, body) sections before joining with blank lines."""
    model_id = active_llm_model or "unknown"
    resolved_terminal_tool = _resolve_terminal_command_tool(
        is_windows=is_windows,
        terminal_tool_name=terminal_tool_name,
    )
    shell_is_powershell = resolved_terminal_tool == "execute_powershell"

    identity_line = (
        agent_identity.strip()
        if agent_identity.strip()
        else "You are Grinta, an expert AI coding agent built by Youssef Mejdi."
    )
    sections: list[tuple[str, str]] = [
        (
            "identity_header",
            f"{identity_line} "
            "You solve complex technical tasks through methodical reasoning and tool execution.\n\n"
            "**Model identity:** The deployment calls you through an API using the configured "
            "model id below.\n"
            f"Configured model id: `{model_id}`",
        ),
    ]

    if windows_with_bash:
        sections.append(
            (
                "shell_identity_git_bash_windows",
                "<SHELL_IDENTITY>\n"
                "Your terminal is **Git Bash** running on Windows. Use **bash syntax exclusively**.\n"
                "- Allowed tools: `ls`, `cat`, `grep`, `find`, `echo`, `cd`, `mkdir`, `rm`, `pwd`, `which`.\n"
                "  (Prefer native tools from the **TOOL_ROUTING_LADDER** first.)\n"
                "- FORBIDDEN: `Get-ChildItem`, `Get-Process`, `Get-Content`, `Select-String`, "
                "`$PSVersionTable`, `Write-Output`, `Set-Location`, or any other PowerShell cmdlet.\n"
                "- Windows-style paths (`C:\\Users\\...`) in the working directory are normal.\n"
                "- Use `which <tool>` to check if on PATH.\n"
                "- Use `python` (not `python3`) to invoke Python.\n"
                "</SHELL_IDENTITY>",
            )
        )
    elif shell_is_powershell:
        sections.append(
            (
                "shell_identity_powershell_windows",
                "<SHELL_IDENTITY>\n"
                "Your terminal is **PowerShell** on Windows. Use PowerShell syntax: chain with `;` (not `&&` / `||`); "
                "prefer `-ErrorAction SilentlyContinue` or `try/catch` instead of `|| true`; use `Start-Process` / "
                "`Start-Job` instead of a trailing `&`.\n\n"
                "**Directory/Content listing:** You may use `Get-ChildItem` (or `ls`, `dir`) and `Select-String` if needed, "
                "but prefer native tools from the **TOOL_ROUTING_LADDER** (`search_code`, editors, structure tools) first.\n\n"
                "**Do not use Unix-only habits here:** `find`, `cat`, `grep`, `head`, `tail`, `touch`, `rm -rf`, "
                "`pkill`, `timeout`, `which`, or `&&` / `||`.\n"
                "</SHELL_IDENTITY>",
            )
        )
    elif not is_windows:
        sections.append(
            (
                "shell_identity_unix",
                "<SHELL_IDENTITY>\n"
                "Your terminal is **Bash / Zsh** running on a Unix-like system. Use standard bash syntax.\n"
                "You may use shell tools (grep, cat, ls, find) if needed, but prefer native tools first.\n"
                "</SHELL_IDENTITY>",
            )
        )

    sections += [
        (
            "system_partial_00_routing",
            _render_routing(shell_is_powershell, config, function_calling_mode),
        ),
        ("security_risk_policy", _render_security(cli_mode)),
        ("system_partial_01_autonomy", _render_autonomy(config, shell_is_powershell)),
        (
            "system_partial_02_tools",
            _render_tool_reference(shell_is_powershell, config),
        ),
        (
            "mcp_permissions_partial_03_tail",
            _render_mcp_and_permissions(
                mcp_tool_names or [],
                mcp_tool_descriptions or {},
                mcp_server_hints or [],
                config,
            ),
        ),
        (
            "system_partial_04_critical",
            _render_critical(
                resolved_terminal_tool,
                enable_think=bool(getattr(config, "enable_think", False)),
                terminal_manager_available=bool(
                    getattr(config, "enable_terminal", True)
                ),
            ),
        ),
    ]
    return sections


def measure_system_prompt_sections(
    *,
    active_llm_model: str = "",
    is_windows: bool = False,
    windows_with_bash: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    terminal_tool_name: str | None = None,
    function_calling_mode: str | None = None,
    agent_identity: str = "",
) -> dict[str, Any]:
    """Token/char budget per section (tiktoken when available). Sections sorted by tokens descending."""
    mid = active_llm_model or "unknown"
    sections = _collect_system_prompt_sections(
        active_llm_model=active_llm_model,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        cli_mode=cli_mode,
        config=config,
        mcp_tool_names=mcp_tool_names,
        mcp_tool_descriptions=mcp_tool_descriptions,
        mcp_server_hints=mcp_server_hints,
        terminal_tool_name=terminal_tool_name,
        function_calling_mode=function_calling_mode,
        agent_identity=agent_identity,
    )
    per: list[dict[str, Any]] = []
    for name, body in sections:
        tok, enc = _count_section_tokens(body, mid)
        per.append({"name": name, "tokens": tok, "chars": len(body), "encoding": enc})
    per.sort(key=lambda r: r["tokens"], reverse=True)
    joined = "\n\n".join(body for _, body in sections)
    tot, enc_tot = _count_section_tokens(joined, mid)
    return {
        "model_id": mid,
        "sections": per,
        "total_tokens": tot,
        "total_chars": len(joined),
        "total_encoding": enc_tot,
    }


def build_system_prompt(
    *,
    active_llm_model: str = "",
    is_windows: bool = False,
    windows_with_bash: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    terminal_tool_name: str | None = None,
    function_calling_mode: str | None = None,
    agent_identity: str = "",
    **_extra: object,
) -> str:
    """Assemble the full system prompt from partials.

    Drop-in replacement for the old ``system_prompt`` rendering.
    """
    sections = _collect_system_prompt_sections(
        active_llm_model=active_llm_model,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        cli_mode=cli_mode,
        config=config,
        mcp_tool_names=mcp_tool_names,
        mcp_tool_descriptions=mcp_tool_descriptions,
        mcp_server_hints=mcp_server_hints,
        terminal_tool_name=terminal_tool_name,
        function_calling_mode=function_calling_mode,
        agent_identity=agent_identity,
    )
    return "\n\n".join(body for _, body in sections)


def build_workspace_context(
    repository_info: RepositoryInfo | None = None,
    runtime_info: RuntimeInfo | None = None,
    conversation_instructions: ConversationInstructions | None = None,
    repo_instructions: str = "",
) -> str:
    """Render the additional-info / workspace context block."""
    parts: list[str] = []

    if repository_info:
        repo_name = getattr(repository_info, "repo_name", None) or ""
        repo_dir = getattr(repository_info, "repo_directory", None) or ""
        branch = getattr(repository_info, "branch_name", None) or ""
        lines = [
            "<REPOSITORY_INFO>",
            f"At the user's request, repository {repo_name} has been cloned to {repo_dir} in the current working directory.",
        ]
        if branch:
            lines.append(f'The repository has been checked out to branch "{branch}".')
            lines.append("")
            lines.append(
                f'IMPORTANT: You should work within the current branch "{branch}" unless\n'
                "    1. the user explicitly instructs otherwise\n"
                '    2. if the current branch is "main", "master", or another default branch '
                "where direct pushes may be unsafe"
            )
        lines.append("</REPOSITORY_INFO>")
        parts.append("\n".join(lines))

    if repo_instructions:
        parts.append(
            f"<REPOSITORY_INSTRUCTIONS>\n{repo_instructions}\n</REPOSITORY_INSTRUCTIONS>"
        )

    if runtime_info:
        ri_lines: list[str] = ["<RUNTIME_INFORMATION>"]
        wd = getattr(runtime_info, "working_dir", "") or ""
        if wd:
            ri_lines.append(f"The current working directory is {wd}")
            ri_lines.append(
                "The open project lives in that directory. Use file and shell paths relative to "
                "it, or absolute paths on disk that stay under it."
            )
            ri_lines.append(
                "There is no `/workspace` virtual path — tools and shell commands use real paths only."
            )
            ri_lines.append(
                "This message does not list project files—do not assume paths like "
                "`tailwind.config.*` exist. Use `search_code` to discover layout, "
                "then read with editor/view tools."
            )

        hosts = getattr(runtime_info, "available_hosts", None) or {}
        if hosts:
            ri_lines.append(
                "The user has access to the following hosts for accessing a web application, "
                "each of which has a corresponding port:"
            )
            for host, port in hosts.items():
                ri_lines.append(f"* {host} (port {port})")
            ri_lines.append(
                "When starting a web server, use the corresponding ports. You should also "
                "set any options to allow iframes and CORS requests, and allow the server to "
                "be accessed from any host (e.g. 0.0.0.0).\n"
                "For example, if you are using vite.config.js, you should set server.host "
                "and server.allowedHosts to true"
            )

        extra_instr = getattr(runtime_info, "additional_agent_instructions", "") or ""
        if extra_instr:
            ri_lines.append(extra_instr)

        secrets = getattr(runtime_info, "custom_secrets_descriptions", None) or {}
        if secrets:
            ri_lines.append("<CUSTOM_SECRETS>")
            ri_lines.append("You have access to the following environment variables")
            for name, desc in secrets.items():
                ri_lines.append(f"* $**{name}**: {desc}")
            ri_lines.append("</CUSTOM_SECRETS>")

        date = getattr(runtime_info, "date", "") or ""
        if date:
            ri_lines.append(f"Today's date is {date} (UTC).")

        ri_lines.append("</RUNTIME_INFORMATION>")
        parts.append("\n".join(ri_lines))

        conv = conversation_instructions
        if conv is not None and conv.content:
            parts.append(
                f"<CONVERSATION_INSTRUCTIONS>\n{conv.content}\n</CONVERSATION_INSTRUCTIONS>"
            )

    return "\n".join(parts).strip()


def build_playbook_info(triggered_agents: list[Any]) -> str:
    """Render playbook info blocks for triggered agents."""
    blocks: list[str] = []
    for agent_info in triggered_agents:
        name = getattr(agent_info, "name", "")
        trigger = getattr(agent_info, "trigger", "")
        content = getattr(agent_info, "content", "")
        intro = (
            f'The following information has been included from playbook "{name}" based on a keyword match for "{trigger}".\n'
            if name
            else f'The following information has been included based on a keyword match for "{trigger}".\n'
        )
        blocks.append(
            f"<EXTRA_INFO>\n"
            f"{intro}"
            f"It may or may not be relevant to the user's request.\n\n"
            f"{content}\n"
            f"</EXTRA_INFO>"
        )
    return "\n".join(blocks).strip()


def build_knowledge_base_info(kb_results: list[Any]) -> str:
    """Render knowledge base search results."""
    blocks: list[str] = []
    for result in kb_results:
        filename = getattr(result, "filename", "")
        score = getattr(result, "relevance_score", 0.0)
        chunk = getattr(result, "chunk_content", "")
        blocks.append(
            f"<KNOWLEDGE_BASE_INFO>\n"
            f"The following information was found in your knowledge base (Document: {filename}).\n"
            f"Relevance score: {score:.2f}\n\n"
            f"{chunk}\n"
            f"</KNOWLEDGE_BASE_INFO>"
        )
    return "\n".join(blocks).strip()


def build_remember_prompt_template(events: str) -> str:
    """Render the remember-prompt template."""
    return (
        "You are tasked with generating a prompt that will be used by another AI to revise a special reference file. "
        "This file contains important information and learnings that are used to carry out certain tasks. "
        "The file can be extended over time to incorporate new knowledge and experiences.\n\n"
        "You have been provided with a subset of new events that may require changes to the special file. "
        "These events are:\n"
        "<events>\n"
        f"{events}\n"
        "</events>\n\n"
        "Your task is to analyze these events and determine what changes, if any, should be made to the special file. "
        "Then, you need to generate a prompt that will instruct another AI to make these revisions correctly and efficiently.\n\n"
        "When creating your prompt, follow these guidelines:\n"
        "1. Clearly specify which parts of the file need to be revised or if new sections should be added.\n"
        "2. Provide context for why these changes are necessary based on the new events.\n"
        "3. Be specific about the information that should be added or modified.\n"
        "4. Maintain the existing structure and formatting of the file.\n"
        "5. Ensure that the revisions are consistent with the current content and don't contradict existing information.\n\n"
        "Now, based on the new events provided, generate a prompt that will guide the AI in making the appropriate "
        "revisions to the special file. Your prompt should be clear, specific, and actionable. "
        "Include your prompt within <revision_prompt> tags.\n\n"
        "<revision_prompt>\n\n</revision_prompt>"
    )


def _cli_measure_default() -> None:
    """Print a default baseline budget (balanced config, no MCP tools)."""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        autonomy_level="balanced",
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_internal_task_tracker=False,
        enable_signal_progress=False,
        enable_permissions=False,
        enable_meta_cognition=False,
    )

    report = measure_system_prompt_sections(
        active_llm_model="gpt-4",
        is_windows=False,
        config=cfg,
        mcp_tool_names=[],
        mcp_tool_descriptions={},
        mcp_server_hints=[],
        function_calling_mode="native",
    )
    print(
        f'model_id={report["model_id"]} total_tokens≈{report["total_tokens"]} ({report["total_encoding"]}) chars={report["total_chars"]}'
    )
    print("section".ljust(42), "tokens", "chars")
    for row in report["sections"]:
        print(row["name"][:41].ljust(42), row["tokens"], row["chars"])


if __name__ == "__main__":
    _cli_measure_default()
