"""Error pattern database — store and query error→solution patterns.

Persists to ``.forge/error_patterns.json`` alongside agent_notes.json.
Each pattern has a ``trigger`` (regex or substring match on error text)
and a ``solution`` (human-readable fix description).  The agent can
``record`` new patterns when it solves errors, and ``query`` the DB
when it hits an error to see if a known fix exists.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from backend.events.action.agent import AgentThinkAction

ERROR_PATTERNS_TOOL_NAME = "error_patterns"

_WORKSPACE_ROOT = os.environ.get("FORGE_WORKSPACE_DIR", ".")
_PATTERNS_FILE = ".forge/error_patterns.json"


def _patterns_path() -> Path:
    return Path(_WORKSPACE_ROOT) / _PATTERNS_FILE


def _load_patterns() -> list[dict]:
    p = _patterns_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_patterns(patterns: list[dict]) -> None:
    p = _patterns_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(patterns, indent=2, ensure_ascii=False), encoding="utf-8")


def create_error_patterns_tool() -> dict:
    """Return the OpenAI function-calling schema for error_patterns."""
    return {
        "type": "function",
        "function": {
            "name": ERROR_PATTERNS_TOOL_NAME,
            "description": (
                "Store and query error→solution patterns. Use 'record' to save a "
                "pattern after solving a novel error. Use 'query' when you hit an "
                "error to check for known fixes. Use 'list' to see all patterns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "description": "One of: record | query | list | delete",
                        "type": "string",
                        "enum": ["record", "query", "list", "delete"],
                    },
                    "trigger": {
                        "description": (
                            "For 'record': regex or substring to match error text. "
                            "For 'query': the error text to search against. "
                            "For 'delete': the trigger pattern to remove."
                        ),
                        "type": "string",
                    },
                    "solution": {
                        "description": "For 'record': the fix/solution description.",
                        "type": "string",
                    },
                },
                "required": ["command"],
            },
        },
    }


def build_error_patterns_action(arguments: dict) -> AgentThinkAction:
    """Execute an error_patterns command and return a think action with results."""
    command = arguments.get("command", "list")
    trigger = arguments.get("trigger", "")
    solution = arguments.get("solution", "")

    if command == "record":
        return _record_pattern(trigger, solution)
    elif command == "query":
        return _query_patterns(trigger)
    elif command == "delete":
        return _delete_pattern(trigger)
    else:
        return _list_patterns()


def _record_pattern(trigger: str, solution: str) -> AgentThinkAction:
    if not trigger or not solution:
        return AgentThinkAction(
            thought="[ERROR_PATTERNS] record requires both 'trigger' and 'solution'."
        )
    patterns = _load_patterns()
    # Avoid exact duplicates
    for p in patterns:
        if p.get("trigger") == trigger:
            p["solution"] = solution
            _save_patterns(patterns)
            return AgentThinkAction(
                thought=f"[ERROR_PATTERNS] Updated existing pattern: {trigger}"
            )
    patterns.append({"trigger": trigger, "solution": solution})
    _save_patterns(patterns)
    return AgentThinkAction(
        thought=f"[ERROR_PATTERNS] Recorded new pattern: {trigger} → {solution}"
    )


def _query_patterns(error_text: str) -> AgentThinkAction:
    if not error_text:
        return AgentThinkAction(
            thought="[ERROR_PATTERNS] query requires 'trigger' (the error text to match)."
        )
    patterns = _load_patterns()
    matches: list[str] = []
    for p in patterns:
        pat = p.get("trigger", "")
        sol = p.get("solution", "")
        try:
            if re.search(pat, error_text, re.IGNORECASE):
                matches.append(f"  • {pat} → {sol}")
        except re.error:
            if pat.lower() in error_text.lower():
                matches.append(f"  • {pat} → {sol}")
    if matches:
        result = "[ERROR_PATTERNS] Known fixes:\n" + "\n".join(matches)
    else:
        result = "[ERROR_PATTERNS] No known patterns match this error."
    return AgentThinkAction(thought=result)


def _delete_pattern(trigger: str) -> AgentThinkAction:
    if not trigger:
        return AgentThinkAction(
            thought="[ERROR_PATTERNS] delete requires 'trigger'."
        )
    patterns = _load_patterns()
    before = len(patterns)
    patterns = [p for p in patterns if p.get("trigger") != trigger]
    _save_patterns(patterns)
    removed = before - len(patterns)
    return AgentThinkAction(
        thought=f"[ERROR_PATTERNS] Removed {removed} pattern(s) with trigger: {trigger}"
    )


def _list_patterns() -> AgentThinkAction:
    patterns = _load_patterns()
    if not patterns:
        return AgentThinkAction(
            thought="[ERROR_PATTERNS] No patterns recorded yet."
        )
    lines = [f"  {i+1}. {p['trigger']} → {p['solution']}" for i, p in enumerate(patterns)]
    return AgentThinkAction(
        thought="[ERROR_PATTERNS] Stored patterns:\n" + "\n".join(lines)
    )
