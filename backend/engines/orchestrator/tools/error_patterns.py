"""Error pattern database — store and query error→solution patterns.

Persists to ``.forge/error_patterns.json`` alongside agent_notes.json.

Cross-session persistence:
  High-confidence patterns (``global: true``) are ALSO written to
  ``~/.forge/global_error_patterns.json`` so they survive across workspaces.
  On every ``query`` call, both local and global patterns are searched.
  This means a fix discovered in project A is automatically available in
  project B without any manual steps.

Each pattern has:
  - ``trigger``  — regex or substring to match error text
  - ``solution`` — human-readable fix description
  - ``global``   — bool; if true, mirrored to ~/.forge/global_error_patterns.json
"""

from __future__ import annotations
from backend.core.config.utils import load_forge_config


import json
import os
import re
from pathlib import Path

from backend.events.action.agent import AgentThinkAction

ERROR_PATTERNS_TOOL_NAME = "error_patterns"

_WORKSPACE_ROOT = load_forge_config(set_logging_levels=False).workspace_base or "."
_PATTERNS_FILE = ".forge/error_patterns.json"
_GLOBAL_PATTERNS_FILE = Path.home() / ".forge" / "global_error_patterns.json"


def _patterns_path() -> Path:
    return Path(_WORKSPACE_ROOT) / _PATTERNS_FILE


def _load_patterns() -> list[dict]:
    """Load local patterns, then merge in global patterns (deduplicated by trigger)."""
    local = _load_file_patterns(_patterns_path())
    global_patterns = _load_file_patterns(_GLOBAL_PATTERNS_FILE)
    # Merge: local takes precedence over global for the same trigger
    local_triggers = {p.get("trigger") for p in local}
    merged = list(local)
    for gp in global_patterns:
        if gp.get("trigger") not in local_triggers:
            merged.append(gp)
    return merged


def _load_file_patterns(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_patterns(patterns: list[dict]) -> None:
    """Save local patterns. Also write global=True patterns to the global store."""
    p = _patterns_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(patterns, indent=2, ensure_ascii=False), encoding="utf-8")

    # Mirror high-confidence patterns to global store
    global_candidates = [pat for pat in patterns if pat.get("global")]
    if global_candidates:
        _merge_into_global(global_candidates)


def _merge_into_global(new_patterns: list[dict]) -> None:
    """Merge new_patterns into the user-level global store (dedup by trigger)."""
    try:
        _GLOBAL_PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_file_patterns(_GLOBAL_PATTERNS_FILE)
        existing_triggers = {p.get("trigger") for p in existing}
        changed = False
        for pat in new_patterns:
            if pat.get("trigger") in existing_triggers:
                # Update the existing entry
                for ep in existing:
                    if ep.get("trigger") == pat.get("trigger"):
                        ep.update(pat)
                        changed = True
                        break
            else:
                existing.append(pat)
                changed = True
        if changed:
            _GLOBAL_PATTERNS_FILE.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    except OSError:
        pass  # Non-fatal: global store write failure doesn't break local workflow


def create_error_patterns_tool() -> dict:
    """Return the OpenAI function-calling schema for error_patterns."""
    return {
        "type": "function",
        "function": {
            "name": ERROR_PATTERNS_TOOL_NAME,
            "description": (
                "Store and query error→solution patterns. Use 'record' to save a "
                "pattern after solving a novel error. Use 'query' when you hit an "
                "error to check for known fixes. Use 'list' to see all patterns.\n\n"
                "Cross-session: set global=true when recording to persist the pattern "
                "across all projects (stored in ~/.forge/global_error_patterns.json). "
                "Queries always search both local and global patterns automatically."
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
                    "global": {
                        "description": (
                            "For 'record': if true, persist this pattern across workspaces "
                            "in ~/.forge/global_error_patterns.json. Use for universal errors "
                            "(e.g. numpy import issues, CUDA mismatches, SSL cert problems). "
                            "Defaults to false (local project only)."
                        ),
                        "type": "boolean",
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
        return _record_pattern(trigger, solution, arguments.get("global", False))
    elif command == "query":
        return _query_patterns(trigger)
    elif command == "delete":
        return _delete_pattern(trigger)
    else:
        return _list_patterns()


def _record_pattern(trigger: str, solution: str, make_global: bool = False) -> AgentThinkAction:
    if not trigger or not solution:
        return AgentThinkAction(
            thought="[ERROR_PATTERNS] record requires both 'trigger' and 'solution'."
        )
    patterns = _load_file_patterns(_patterns_path())  # Load local only for writing
    # Avoid exact duplicates
    for p in patterns:
        if p.get("trigger") == trigger:
            p["solution"] = solution
            if make_global:
                p["global"] = True
            _save_patterns(patterns)
            scope = " (also saved to global store)" if make_global else ""
            return AgentThinkAction(
                thought=f"[ERROR_PATTERNS] Updated existing pattern: {trigger}{scope}"
            )
    entry: dict = {"trigger": trigger, "solution": solution}
    if make_global:
        entry["global"] = True
    patterns.append(entry)
    _save_patterns(patterns)
    scope = " (also saved to global store across all projects)" if make_global else ""
    return AgentThinkAction(
        thought=f"[ERROR_PATTERNS] Recorded new pattern: {trigger} → {solution}{scope}"
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
