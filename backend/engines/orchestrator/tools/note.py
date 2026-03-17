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
from backend.core.config.utils import load_forge_config


import json
import os
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

# Workspace root can be overridden via env for testing; defaults to cwd.
_WORKSPACE_ROOT = load_forge_config(set_logging_levels=False).workspace_base or "."
_NOTES_RELPATH = os.path.join(".forge", "agent_notes.json")


def _notes_path() -> Path:
    """Return the absolute path to the scratchpad JSON file."""
    return Path(_WORKSPACE_ROOT) / _NOTES_RELPATH


def _load_notes() -> dict[str, str]:
    """Load the scratchpad dict, returning {} if missing or corrupt."""
    p = _notes_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_notes(data: dict[str, str]) -> None:
    """Persist the scratchpad dict to disk."""
    p = _notes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_note_action(key: str, value: str) -> AgentThinkAction:
    """Persist key→value to the scratchpad and return a think action with confirmation."""
    notes = _load_notes()
    notes[key] = value
    _save_notes(notes)
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
