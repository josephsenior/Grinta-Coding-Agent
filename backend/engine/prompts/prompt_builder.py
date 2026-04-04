"""Pure-Python prompt builder — replaces Jinja2 template rendering.

Each template partial is a function that returns a string.  Static
sections are loaded from .md files on disk; dynamic sections are
assembled via f-strings and simple loops.

Public API
----------
build_system_prompt(**ctx)   → full system prompt string
build_workspace_context(...) → additional_info block
build_playbook_info(...)     → playbook block
build_knowledge_base_info(.) → knowledge-base block
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.utils.prompt import RepositoryInfo, RuntimeInfo, ConversationInstructions

_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _load(name: str) -> str:
    """Read a .md partial from the prompts directory and cache it."""
    return (_DIR / name).read_text(encoding="utf-8").strip()


def _choose(is_windows: bool, win: str, unix: str) -> str:
    return win if is_windows else unix


# ---------------------------------------------------------------------------
# system_partial_00_routing
# ---------------------------------------------------------------------------

def _render_routing(is_windows: bool) -> str:
    ls_cmd = _choose(is_windows, "`Get-ChildItem -Force`", "`ls -F`")
    batch_cmds = _choose(
        is_windows,
        "Combine `Get-ChildItem`, `Get-Content`, `Select-String` in one shell where possible.",
        "Combine `ls && cat && grep` in one bash line where possible.",
    )
    return _load("system_partial_00_routing.md").format(
        ls_command=ls_cmd,
        batch_commands=batch_cmds,
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
    cp_line = " Checkpoints allow rollback of risky ops." if checkpoints else ""

    if level == "full":
        autonomy = (
            f"<AUTONOMY>\nFULL AUTONOMOUS MODE: Execute routine work without confirmation; "
            f"auto-retry recoverable errors; ask only when critically ambiguous; complete end-to-end.{cp_line}\n</AUTONOMY>"
        )
    elif level == "supervised":
        autonomy = (
            f"<AUTONOMY>\nSUPERVISED MODE: Confirm before risky ops (delete, git push, system); "
            f"keep user informed; wait when uncertain.{cp_line}\n</AUTONOMY>"
        )
    else:
        autonomy = (
            f"<AUTONOMY>\nBALANCED MODE: Routine ops autonomous; confirm high-risk / irreversible actions only.{cp_line}\n</AUTONOMY>"
        )

    ls_cmd = _choose(is_windows, "Get-ChildItem", "ls/find")
    return _load("system_partial_01_autonomy.md").format(
        autonomy_block=autonomy,
        ls_command=ls_cmd,
    )


# ---------------------------------------------------------------------------
# system_partial_02_tool_reference
# ---------------------------------------------------------------------------

def _render_tool_reference(is_windows: bool) -> str:
    confirm_cmd = _choose(is_windows, "Confirm paths with `Get-ChildItem` when unsure.", "Confirm with `ls` when unsure.")
    proc_find = _choose(
        is_windows,
        "Find: `Get-Process | Where-Object { $_.ProcessName -like '*name*' }`; kill: `Stop-Process -Id <PID>`.",
        "Never `pkill -f` broadly — `ps`/`grep` then `kill <PID>`.",
    )
    return _load("system_partial_02_tools.md").format(
        confirm_paths=confirm_cmd,
        process_management=proc_find,
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
        cap = 24
        show_desc = total <= 12

        parts.append(
            f'🔌 **External MCP tools** ({total}): use **`call_mcp_tool(tool_name="...", arguments={{...}})`** '
            f"— argument shapes match the registered tool schema."
        )
        for name in mcp_tool_names[:cap]:
            if show_desc and name in mcp_tool_descriptions:
                parts.append(f"- `{name}`: {mcp_tool_descriptions[name]}")
            else:
                parts.append(f"- `{name}`")
        if total > cap:
            parts.append(f"- … and **{total - cap}** more (names in tool list / `call_mcp_tool` only).")

        if mcp_server_hints:
            parts.append("")
            parts.append("<MCP_SERVER_HINTS>")
            parts.append("**Configured MCP servers (when to use each — from your MCP settings):**")
            for row in mcp_server_hints:
                parts.append(f"- **`{row['server']}`:** {row['hint']}")
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
            'Prefer **`call_mcp_tool`** over shell one-offs when an MCP tool covers the need. '
            "If asked what you can do or which models/tools you have, answer from **this** tool list, "
            "**MCP server hints** (if any), and your configured model id—**not** generic \"no web / no docs\" tropes."
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
    parts.append("")
    parts.append(_load("system_partial_03_tail.md"))

    return "\n".join(parts)


def _render_permissions(config: Any, perm: Any) -> str:
    """Render the <PERMISSIONS> block from config.permissions."""
    file_w = "WRITE" if getattr(perm, "file_write_enabled", False) else "READ-ONLY"
    if getattr(perm, "file_write_enabled", False):
        file_w += f" (max {getattr(perm, 'file_operations_max_size_mb', '?')}MB)"
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
    if getattr(perm, "shell_enabled", False) and getattr(perm, "shell_allow_sudo", False):
        shell_str += " + SUDO"
    shell_blocked = ", ".join(getattr(perm, "shell_blocked_commands", []))

    net_str = "DISABLED"
    if getattr(perm, "network_enabled", False):
        net_str = f"{getattr(perm, 'network_max_requests_per_minute', '?')}/min"
        domains = getattr(perm, "network_allowed_domains", [])
        if domains:
            net_str += f" | Only: {', '.join(domains)}"

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

def build_system_prompt(
    *,
    active_llm_model: str = "",
    is_windows: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    **_extra: object,
) -> str:
    """Assemble the full system prompt from partials.

    Drop-in replacement for the old ``system_prompt`` rendering.
    """
    model_id = active_llm_model or "unknown"

    sections = [
        # Identity
        "You are Grinta, an expert AI coding agent built by Youssef Mejdi (josephsenior on GitHub). "
        "You solve complex technical tasks through methodical reasoning and tool execution.\n\n"
        "**Model identity:** The deployment calls you through an API using the configured "
        "model id below. When the user asks what model you are, clarify: you are **Grinta** (the agent), "
        "powered by the configured model. Do **not** claim to be a different commercial product "
        "(e.g. \"Claude Sonnet\", \"GPT-4\") unless that exact string is the configured id. "
        "When asked who built you or who you are, you are Grinta, built by Youssef Mejdi.\n\n"
        f"Configured model id: `{model_id}`",
        # Routing
        _render_routing(is_windows),
        # Security
        _render_security(cli_mode),
        # Autonomy & execution
        _render_autonomy(config, is_windows),
        # Tool reference
        _render_tool_reference(is_windows),
        # MCP & permissions tail
        _render_mcp_and_permissions(
            mcp_tool_names or [],
            mcp_tool_descriptions or {},
            mcp_server_hints or [],
            config,
        ),
        # Critical rules (last for recency)
        _load("system_partial_04_critical.md"),
    ]

    return "\n\n".join(sections)


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
        parts.append(f"<REPOSITORY_INSTRUCTIONS>\n{repo_instructions}\n</REPOSITORY_INSTRUCTIONS>")

    if runtime_info:
        ri_lines: list[str] = ["<RUNTIME_INFORMATION>"]
        wd = getattr(runtime_info, "working_dir", "") or ""
        if wd:
            ri_lines.append(f"The current working directory is {wd}")

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
            ri_lines.append("You are have access to the following environment variables")
            for name, desc in secrets.items():
                ri_lines.append(f"* $**{name}**: {desc}")
            ri_lines.append("</CUSTOM_SECRETS>")

        date = getattr(runtime_info, "date", "") or ""
        if date:
            ri_lines.append(f"Today's date is {date} (UTC).")

        ri_lines.append("</RUNTIME_INFORMATION>")
        parts.append("\n".join(ri_lines))

        conv = conversation_instructions
        if conv and getattr(conv, "content", ""):
            parts.append(f"<CONVERSATION_INSTRUCTIONS>\n{conv.content}\n</CONVERSATION_INSTRUCTIONS>")

    return "\n".join(parts).strip()


def build_playbook_info(triggered_agents: list[Any]) -> str:
    """Render playbook info blocks for triggered agents."""
    blocks: list[str] = []
    for agent_info in triggered_agents:
        trigger = getattr(agent_info, "trigger", "")
        name = getattr(agent_info, "name", "")
        content = getattr(agent_info, "content", "")
        blocks.append(
            f"<EXTRA_INFO>\n"
            f'The following information has been included based on a keyword match for "{trigger}".\n'
            f"It may or may not be relevant to the user's request.\n\n"
            f'CRITICAL INSTRUCTION: Because this playbook ("{name}") was triggered, you MUST begin your next '
            f"response to the user with the EXACT phrase:\n"
            f'"App is treating this as a [{name}] based on your prompt. Generating plan..."\n\n'
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
    """Render the remember-prompt template (replaces generate_remember_prompt.j2)."""
    return (
        "You are tasked with generating a prompt that will be used by another AI to update a special reference file. "
        "This file contains important information and learnings that are used to carry out certain tasks. "
        "The file can be extended over time to incorporate new knowledge and experiences.\n\n"
        "You have been provided with a subset of new events that may require updates to the special file. "
        "These events are:\n"
        "<events>\n"
        f"{events}\n"
        "</events>\n\n"
        "Your task is to analyze these events and determine what updates, if any, should be made to the special file. "
        "Then, you need to generate a prompt that will instruct another AI to make these updates correctly and efficiently.\n\n"
        "When creating your prompt, follow these guidelines:\n"
        "1. Clearly specify which parts of the file need to be updated or if new sections should be added.\n"
        "2. Provide context for why these updates are necessary based on the new events.\n"
        "3. Be specific about the information that should be added or modified.\n"
        "4. Maintain the existing structure and formatting of the file.\n"
        "5. Ensure that the updates are consistent with the current content and don't contradict existing information.\n\n"
        "Now, based on the new events provided, generate a prompt that will guide the AI in making the appropriate "
        "updates to the special file. Your prompt should be clear, specific, and actionable. "
        "Include your prompt within <update_prompt> tags.\n\n"
        "<update_prompt>\n\n</update_prompt>"
    )
