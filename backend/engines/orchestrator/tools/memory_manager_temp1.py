"""Persistent scratchpad tools — note(), recall(), semantic_recall() — for the Orchestrator agent.

Notes are stored in ``.forge/agent_notes.json`` inside the workspace root and
survive context condensation.  The LLM can store arbitrary key→value pairs
(decisions, interim results, discovered facts) and retrieve them at any time.

``semantic_recall`` queries the in-memory vector store for semantically
similar past context (conversation fragments, decisions, observations).
The handler returns an ``AgentThinkAction`` whose thought is resolved by
the orchestrator into actual results from ``ConversationMemory.recall_from_memory``.

Implementation note
-------------------
note/recall are now executed natively in-process using direct file I/O
and return ``AgentThinkAction`` results.  No shell round-trip is needed,
which eliminates latency, encoding concerns, and sandbox permission issues.
"""

from __future__ import annotations
import json
import os
import time
from pathlib import Path

from backend.core.constants import NOTE_TOOL_NAME, RECALL_TOOL_NAME, SEMANTIC_RECALL_TOOL_NAME
from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action import AgentThinkAction

# ---------------------------------------------------------------------------
# Tool descriptions
# ---------------------------------------------------------------------------

_NOTE_DESCRIPTION = (
    "Store a persistent note in your scratchpad. "
    "Notes are written to .forge/agent_notes.json inside the workspace root "
    "and survive context condensation — use them to remember decisions, "
    "constraints, or interim findings across a long session.\n\n"
    "Examples: key='auth_decision', value='using JWT with 1-hour expiry'.\n"
    "          key='db_url',        value='postgres://localhost/myapp'."
)

_RECALL_DESCRIPTION = (
    "Retrieve a value from your persistent scratchpad.\n\n"
    "Pass a specific key to get one value, or key=\"all\" to dump the entire scratchpad."
)

_SEMANTIC_RECALL_DESCRIPTION = (
    "Search your long-term vector memory for semantically related past context. "
    "Unlike 'recall' (which retrieves exact key→value pairs from the scratchpad), "
    "this tool performs a semantic similarity search across all conversation history, "
    "decisions, and observations stored in the vector store.\n\n"
    "Use this after context condensation to recover specific details, or when you "
    "need to find earlier conversation fragments related to a topic.\n\n"
    "Examples: query='database migration strategy', k=5\n"
    "          query='user's authentication requirements', k=3"
)


# ---------------------------------------------------------------------------
# Tool definitions (JSON schemas sent to the LLM)
# ---------------------------------------------------------------------------

def create_note_tool() -> ChatCompletionToolParam:
    """Create the persistent-note tool definition."""
    return create_tool_definition(
        name=NOTE_TOOL_NAME,
        description=_NOTE_DESCRIPTION,
        properties={
            "key": {
                "type": "string",
                "description": (
                    "Short identifier for this note "
                    "(e.g. 'auth_decision', 'db_schema', 'test_command')."
                ),
            },
            "value": {
                "type": "string",
                "description": "The value to store. May be multi-line, any text.",
            },
        },
        required=["key", "value"],
    )


def create_recall_tool() -> ChatCompletionToolParam:
    """Create the scratchpad-recall tool definition."""
    return create_tool_definition(
        name=RECALL_TOOL_NAME,
        description=_RECALL_DESCRIPTION,
        properties={
            "key": {
                "type": "string",
                "description": (
                    'The key to retrieve. Use "all" to list every stored note.'
                ),
            },
        },
        required=["key"],
    )


def create_semantic_recall_tool() -> ChatCompletionToolParam:
    """Create the semantic vector-memory recall tool definition."""
    return create_tool_definition(
        name=SEMANTIC_RECALL_TOOL_NAME,
        description=_SEMANTIC_RECALL_DESCRIPTION,
        properties={
            "query": {
                "type": "string",
                "description": (
                    "Natural language query describing what you want to recall "
                    "(e.g. 'database migration strategy', 'user auth requirements')."
                ),
            },
            "k": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10).",
            },
        },
        required=["query"],
    )


# ---------------------------------------------------------------------------
# Native action builders (called from function_calling.py)
# ---------------------------------------------------------------------------

_NOTES_RELPATH = os.path.join(".forge", "agent_notes.json")
# Reserved top-level key for per-key update timestamps (prompt injection recency).
_SCRATCHPAD_META_KEY = "__forge_scratchpad_meta__"


def _notes_path() -> Path:
    """Return the absolute path to the scratchpad JSON file."""
    from backend.core.workspace_resolution import require_effective_workspace_root

    return require_effective_workspace_root() / _NOTES_RELPATH


def _read_notes_blob() -> dict:
    """Load raw JSON object from disk, or {} if missing/corrupt."""
    p = _notes_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_notes_blob(raw: dict) -> tuple[dict[str, str], dict[str, float]]:
    """Split user notes from internal metadata; coerce timestamps to float."""
    blob = dict(raw)
    meta = blob.pop(_SCRATCHPAD_META_KEY, None)
    updated: dict[str, float] = {}
    if isinstance(meta, dict):
        u = meta.get("updated")
        if isinstance(u, dict):
            for k, v in u.items():
                if isinstance(k, str) and isinstance(v, (int, float)):
                    updated[k] = float(v)
    notes: dict[str, str] = {}
    for k, v in blob.items():
        if isinstance(v, str):
            notes[k] = v
    return notes, updated


def _write_notes_blob(notes: dict[str, str], updated: dict[str, float]) -> None:
    """Persist notes plus update timestamps (for recency ordering in prompts)."""
    p = _notes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out: dict = {**notes, _SCRATCHPAD_META_KEY: {"updated": updated}}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def _load_notes() -> dict[str, str]:
    """Load user-visible scratchpad keys only (no internal metadata)."""
    return _parse_notes_blob(_read_notes_blob())[0]


def scratchpad_entries_for_prompt() -> list[tuple[str, str]]:
    """Return (key, value) pairs for system-prompt injection: deduped, newest first.

    - Case-insensitive keys are collapsed; the variant with the latest ``updated``
      timestamp wins (or arbitrary among ties).
    - When no timestamps exist (legacy file), entries are sorted alphabetically by key.
    """
    notes, ts = _parse_notes_blob(_read_notes_blob())
    merged: dict[str, tuple[str, str, float]] = {}
    for k, v in notes.items():
        ks = k.strip()
        if not ks:
            continue
        t = float(ts.get(k, 0.0))
        cf = ks.casefold()
        prev = merged.get(cf)
        if prev is None or t >= prev[2]:
            merged[cf] = (ks, v, t)
    rows = list(merged.values())
    if rows and any(r[2] > 0.0 for r in rows):
        rows.sort(key=lambda r: r[2], reverse=True)
    else:
        rows.sort(key=lambda r: r[0].casefold())
    return [(r[0], r[1]) for r in rows]


def build_note_action(key: str, value: str) -> AgentThinkAction:
    """Persist key→value to the scratchpad and return a think action with confirmation."""
    notes, updated = _parse_notes_blob(_read_notes_blob())
    notes[key] = value
    updated[key] = time.time()
    _write_notes_blob(notes, updated)
    return AgentThinkAction(thought=f"[SCRATCHPAD] Noted [{key}]")


def build_recall_action(key: str) -> AgentThinkAction:
    """Retrieve key (or all keys) from the scratchpad, returning the result as thought."""
    notes = _load_notes()
    if key == "all":
        if notes:
            body = json.dumps(notes, indent=2, ensure_ascii=False)
        else:
            body = "(scratchpad is empty)"
        return AgentThinkAction(thought=f"[SCRATCHPAD] All notes:\n{body}")
    if key in notes:
        return AgentThinkAction(thought=f"[SCRATCHPAD] [{key}] = {notes[key]!r}")
    return AgentThinkAction(thought=f"[SCRATCHPAD] (no note for [{key}])")


# ---------------------------------------------------------------------------
# Working memory tool (structured cognitive workspace)
# ---------------------------------------------------------------------------

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action.agent import AgentThinkAction

WORKING_MEMORY_TOOL_NAME = "working_memory"

_MEMORY_FILE = ".forge/working_memory.json"

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

    return require_effective_workspace_root() / _MEMORY_FILE


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
