"""Structured working memory tool — a cognitive workspace that survives condensation.

Unlike the flat key→value scratchpad (note/recall), working memory provides
structured sections that map to how an LLM agent actually thinks:
- hypothesis: current theory or approach
- findings: discovered facts and evidence
- blockers: obstacles and unresolved issues
- file_context: key files and their roles
- decisions: architectural/implementation choices made

All sections persist to ``.forge/working_memory.json`` and are automatically
injected into post-condensation recovery context, ensuring the agent never
loses its cognitive workspace even after history compression.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action.agent import AgentThinkAction

WORKING_MEMORY_TOOL_NAME = "working_memory"

_VALID_SECTIONS = ("hypothesis", "findings", "blockers", "file_context", "decisions", "plan")

_DESCRIPTION = (
    "Maintain a structured cognitive workspace that survives context condensation. "
    "Unlike 'note' (flat key-value), working_memory has typed sections that "
    "represent your current thinking state.\n\n"
    "Sections: hypothesis (current approach), findings (discovered facts), "
    "blockers (obstacles), file_context (key files and roles), "
    "decisions (choices made), plan (current action plan).\n\n"
    "Commands:\n"
    "  update — append or replace content in a section\n"
    "  get — retrieve one section or 'all' for full dump\n"
    "  clear_section — reset a specific section\n\n"
    "Use this to maintain structured context across long sessions. "
    "After condensation, your working memory is automatically restored."
)


def create_working_memory_tool() -> ChatCompletionToolParam:
    """Create the working memory tool definition."""
    return create_tool_definition(
        name=WORKING_MEMORY_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "command": {
                "type": "string",
                "enum": ["update", "get", "clear_section"],
                "description": (
                    "update: set/append content to a section. "
                    "get: retrieve a section (or 'all'). "
                    "clear_section: reset a section."
                ),
            },
            "section": {
                "type": "string",
                "enum": list(_VALID_SECTIONS),
                "description": "The working memory section to operate on.",
            },
            "content": {
                "type": "string",
                "description": "For 'update': the content to store. Replaces existing content in the section.",
            },
        },
        required=["command", "section"],
    )


# --- Persistence ---

def _memory_path() -> Path:
    from backend.core.workspace_resolution import require_effective_workspace_root

    return require_effective_workspace_root() / ".forge" / "working_memory.json"


def _load_memory() -> dict[str, str]:
    p = _memory_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_memory(data: dict[str, str]) -> None:
    p = _memory_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Action builders ---

def build_working_memory_action(arguments: dict) -> AgentThinkAction:
    """Execute a working_memory command and return a think action with results."""
    command = arguments.get("command", "get")
    section = arguments.get("section", "all")
    content = arguments.get("content", "")

    if command == "update":
        return _update_section(section, content)
    elif command == "clear_section":
        return _clear_section(section)
    else:
        return _get_section(section)


def _update_section(section: str, content: str) -> AgentThinkAction:
    if section not in _VALID_SECTIONS:
        return AgentThinkAction(
            thought=f"[WORKING_MEMORY] Invalid section: {section}. Valid: {', '.join(_VALID_SECTIONS)}"
        )
    if not content:
        return AgentThinkAction(
            thought="[WORKING_MEMORY] 'content' is required for update."
        )
    memory = _load_memory()
    memory[section] = content
    memory["_last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_memory(memory)
    return AgentThinkAction(
        thought=f"[WORKING_MEMORY] Updated '{section}' section."
    )


def _get_section(section: str) -> AgentThinkAction:
    memory = _load_memory()
    if not memory:
        return AgentThinkAction(
            thought="[WORKING_MEMORY] Working memory is empty."
        )
    if section == "all":
        parts = ["[WORKING_MEMORY] Full cognitive workspace:"]
        for sec in _VALID_SECTIONS:
            val = memory.get(sec, "")
            if val:
                parts.append(f"\n## {sec.upper()}\n{val}")
        if len(parts) == 1:
            return AgentThinkAction(thought="[WORKING_MEMORY] All sections are empty.")
        last = memory.get("_last_updated", "?")
        parts.append(f"\n(last updated: {last})")
        return AgentThinkAction(thought="\n".join(parts))

    if section not in _VALID_SECTIONS:
        return AgentThinkAction(
            thought=f"[WORKING_MEMORY] Invalid section: {section}. Valid: {', '.join(_VALID_SECTIONS)}"
        )
    val = memory.get(section, "")
    if not val:
        return AgentThinkAction(
            thought=f"[WORKING_MEMORY] '{section}' is empty."
        )
    return AgentThinkAction(
        thought=f"[WORKING_MEMORY] {section}:\n{val}"
    )


def _clear_section(section: str) -> AgentThinkAction:
    if section not in _VALID_SECTIONS:
        return AgentThinkAction(
            thought=f"[WORKING_MEMORY] Invalid section: {section}. Valid: {', '.join(_VALID_SECTIONS)}"
        )
    memory = _load_memory()
    if section in memory:
        del memory[section]
        _save_memory(memory)
    return AgentThinkAction(
        thought=f"[WORKING_MEMORY] Cleared '{section}' section."
    )


def get_full_working_memory() -> str:
    """Load and format working memory for injection into context.

    Used by post-condensation recovery to restore the cognitive workspace.
    Returns an empty string if working memory is empty.
    """
    memory = _load_memory()
    if not memory:
        return ""

    parts = ["<WORKING_MEMORY>"]
    for sec in _VALID_SECTIONS:
        val = memory.get(sec, "")
        if val:
            parts.append(f"[{sec.upper()}] {val}")

    if len(parts) == 1:
        return ""
    parts.append("</WORKING_MEMORY>")
    return "\n".join(parts)
