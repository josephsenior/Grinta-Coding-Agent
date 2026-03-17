"""checkpoint tool — save and restore progress markers.

Persists to ``.forge/checkpoints.json``.  The agent can ``save`` a
checkpoint after completing a logical phase, and ``restore`` to see
what was done.  This complements the task_tracker by providing a
durable progress snapshot that survives condensation.
"""

from __future__ import annotations
from backend.core.config.utils import load_forge_config


import json
import os
import time
from pathlib import Path

from backend.events.action.agent import AgentThinkAction

CHECKPOINT_TOOL_NAME = "checkpoint"

_WORKSPACE_ROOT = load_forge_config(set_logging_levels=False).workspace_base or "."
_CHECKPOINTS_FILE = ".forge/checkpoints.json"


def _checkpoints_path() -> Path:
    return Path(_WORKSPACE_ROOT) / _CHECKPOINTS_FILE


def _load_checkpoints() -> list[dict]:
    p = _checkpoints_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_checkpoints(checkpoints: list[dict]) -> None:
    p = _checkpoints_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(checkpoints, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def create_checkpoint_tool() -> dict:
    """Return the OpenAI function-calling schema for checkpoint."""
    return {
        "type": "function",
        "function": {
            "name": CHECKPOINT_TOOL_NAME,
            "description": (
                "Save or view progress checkpoints. Use 'save' after completing "
                "a logical phase of work (e.g., 'auth module complete'). Use "
                "'view' to see all saved checkpoints. Use 'clear' to reset."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "description": "One of: save | view | clear",
                        "type": "string",
                        "enum": ["save", "view", "clear"],
                    },
                    "label": {
                        "description": "For 'save': short description of what was completed.",
                        "type": "string",
                    },
                    "files_modified": {
                        "description": "For 'save': comma-separated list of files that were changed.",
                        "type": "string",
                    },
                },
                "required": ["command"],
            },
        },
    }


def build_checkpoint_action(arguments: dict) -> AgentThinkAction:
    """Execute a checkpoint command and return a think action with results."""
    command = arguments.get("command", "view")

    if command == "save":
        return _save_checkpoint(
            arguments.get("label", ""),
            arguments.get("files_modified", ""),
        )
    elif command == "clear":
        return _clear_checkpoints()
    else:
        return _view_checkpoints()


def _save_checkpoint(label: str, files_modified: str) -> AgentThinkAction:
    if not label:
        return AgentThinkAction(
            thought="[CHECKPOINT] save requires 'label' describing what was completed."
        )
    checkpoints = _load_checkpoints()
    entry = {
        "id": len(checkpoints) + 1,
        "label": label,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if files_modified:
        entry["files"] = [f.strip() for f in files_modified.split(",")]
    checkpoints.append(entry)
    _save_checkpoints(checkpoints)
    return AgentThinkAction(
        thought=f"[CHECKPOINT] Saved #{entry['id']}: {label}"
    )


def _view_checkpoints() -> AgentThinkAction:
    checkpoints = _load_checkpoints()
    if not checkpoints:
        return AgentThinkAction(
            thought="[CHECKPOINT] No checkpoints saved yet."
        )
    lines: list[str] = []
    for cp in checkpoints:
        files = ", ".join(cp.get("files", []))
        files_str = f" | files: {files}" if files else ""
        lines.append(f"  #{cp['id']} [{cp.get('timestamp', '?')}] {cp['label']}{files_str}")
    return AgentThinkAction(
        thought="[CHECKPOINT] Progress:\n" + "\n".join(lines)
    )


def _clear_checkpoints() -> AgentThinkAction:
    _save_checkpoints([])
    return AgentThinkAction(
        thought="[CHECKPOINT] All checkpoints cleared."
    )
