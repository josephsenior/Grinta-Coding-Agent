"""Pre-condensation snapshot — auto-extracts critical context before condensation.

When condensation fires, the LLM loses all tool outputs and file contents.
This module extracts the most important context from the about-to-be-forgotten
events and persists it to ``.forge/pre_condensation_snapshot.json``.

The snapshot is then injected into the post-condensation recovery sequence,
giving the LLM a structured summary of what was lost — without requiring
the LLM to have manually noted everything.

Extracted context:
- Files read/edited with their last-known action
- Recent error messages and their surrounding context
- Key decisions expressed in think() calls
- Recent command outputs (truncated)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.events.event import Event

_WORKSPACE_ROOT = os.environ.get("FORGE_WORKSPACE_DIR", ".")
_SNAPSHOT_FILE = ".forge/pre_condensation_snapshot.json"

# Limits to prevent the snapshot from becoming too large
_MAX_ERRORS = 10
_MAX_DECISIONS = 15
_MAX_COMMANDS = 10
_MAX_CONTENT_LENGTH = 500


def _snapshot_path() -> Path:
    return Path(_WORKSPACE_ROOT) / _SNAPSHOT_FILE


_MAX_ATTEMPTED_APPROACHES = 20


def extract_snapshot(events: list[Event]) -> dict[str, Any]:
    """Extract critical context from events that are about to be condensed.

    Args:
        events: The events that will be forgotten during condensation.

    Returns:
        A structured dict containing the extracted context.
    """
    snapshot: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "events_condensed": len(events),
        "files_touched": {},
        "recent_errors": [],
        "decisions": [],
        "recent_commands": [],
        "attempted_approaches": [],
    }

    for event in events:
        _extract_file_info(event, snapshot)
        _extract_errors(event, snapshot)
        _extract_decisions(event, snapshot)
        _extract_commands(event, snapshot)

    _extract_attempted_approaches(events, snapshot)

    return snapshot


def _extract_file_info(event: Event, snapshot: dict) -> None:
    """Extract file paths and actions from file-related events."""
    cls_name = type(event).__name__
    files = snapshot["files_touched"]

    if cls_name in ("FileEditAction", "FileEditObservation"):
        path = getattr(event, "path", "")
        if path:
            command = getattr(event, "command", "edit")
            files[path] = {"action": command, "type": "edit"}
    elif cls_name in ("FileReadAction", "FileReadObservation"):
        path = getattr(event, "path", "")
        if path and path not in files:
            files[path] = {"action": "read", "type": "read"}
    elif cls_name == "CmdRunAction":
        cmd = getattr(event, "command", "")
        # Detect file operations in commands
        if "cat " in cmd or "head " in cmd or "tail " in cmd:
            # Best-effort path extraction
            parts = cmd.split()
            for i, part in enumerate(parts):
                if part in ("cat", "head", "tail") and i + 1 < len(parts):
                    path = parts[i + 1].strip("'\"")
                    if path and path not in files:
                        files[path] = {"action": "read_via_cmd", "type": "read"}


def _extract_errors(event: Event, snapshot: dict) -> None:
    """Extract error messages from error observations."""
    if len(snapshot["recent_errors"]) >= _MAX_ERRORS:
        return

    cls_name = type(event).__name__
    if cls_name == "ErrorObservation":
        content = str(getattr(event, "content", ""))[:_MAX_CONTENT_LENGTH]
        if content:
            snapshot["recent_errors"].append(content)
    elif cls_name == "CmdOutputObservation":
        exit_code = getattr(event, "exit_code", 0)
        if exit_code != 0:
            content = str(getattr(event, "content", ""))
            # Extract just the last few lines as the error
            lines = content.strip().split("\n")
            error_tail = "\n".join(lines[-5:])[:_MAX_CONTENT_LENGTH]
            if error_tail:
                snapshot["recent_errors"].append(
                    f"[exit_code={exit_code}] {error_tail}"
                )


def _extract_decisions(event: Event, snapshot: dict) -> None:
    """Extract decisions and key reasoning from think actions."""
    if len(snapshot["decisions"]) >= _MAX_DECISIONS:
        return

    cls_name = type(event).__name__
    if cls_name in ("AgentThinkAction", "AgentThinkObservation"):
        thought = str(getattr(event, "thought", ""))
        # Skip recovery/reflection boilerplate — only capture real decisions
        skip_prefixes = ("⚡ CONTEXT CONDENSED", "🔍 SELF-REFLECTION", "[SCRATCHPAD]", "[SEMANTIC_RECALL")
        if thought and not any(thought.startswith(p) for p in skip_prefixes):
            snapshot["decisions"].append(thought[:_MAX_CONTENT_LENGTH])


def _extract_commands(event: Event, snapshot: dict) -> None:
    """Extract recent command+result pairs."""
    if len(snapshot["recent_commands"]) >= _MAX_COMMANDS:
        return

    cls_name = type(event).__name__
    if cls_name == "CmdRunAction":
        cmd = str(getattr(event, "command", ""))[:_MAX_CONTENT_LENGTH]
        if cmd:
            snapshot["recent_commands"].append({"command": cmd})
    elif cls_name == "CmdOutputObservation":
        # Attach output to the most recent command if available
        commands = snapshot["recent_commands"]
        if commands and "output" not in commands[-1]:
            content = str(getattr(event, "content", ""))
            lines = content.strip().split("\n")
            # Keep first and last few lines
            if len(lines) > 10:
                truncated = lines[:3] + ["... (truncated) ..."] + lines[-3:]
            else:
                truncated = lines
            commands[-1]["output"] = "\n".join(truncated)[:_MAX_CONTENT_LENGTH]


def _extract_attempted_approaches(events: list[Event], snapshot: dict) -> None:
    """Extract action→outcome pairs to build a structured 'attempted approaches' record.

    This captures WHAT was tried and WHETHER it worked, so the LLM can avoid
    retrying failed strategies after condensation.
    """
    approaches = snapshot["attempted_approaches"]
    if len(approaches) >= _MAX_ATTEMPTED_APPROACHES:
        return

    pending_action: dict[str, Any] | None = None

    for event in events:
        cls_name = type(event).__name__

        if cls_name == "FileEditAction":
            path = getattr(event, "path", "")
            command = getattr(event, "command", "edit")
            old_str = str(getattr(event, "old_str", ""))[:80] if hasattr(event, "old_str") else ""
            pending_action = {
                "type": "file_edit",
                "detail": f"{command} on {path}" + (f" (old_str: {old_str!r}...)" if old_str else ""),
            }
        elif cls_name == "CmdRunAction":
            cmd = str(getattr(event, "command", ""))[:150]
            pending_action = {"type": "command", "detail": cmd}
        elif cls_name in ("ErrorObservation",) and pending_action:
            content = str(getattr(event, "content", ""))[:150]
            pending_action["outcome"] = f"FAILED: {content}"
            if len(approaches) < _MAX_ATTEMPTED_APPROACHES:
                approaches.append(pending_action)
            pending_action = None
        elif cls_name == "CmdOutputObservation" and pending_action:
            exit_code = getattr(event, "exit_code", 0)
            if exit_code != 0:
                content = str(getattr(event, "content", ""))
                lines = content.strip().split("\n")
                tail = lines[-1][:150] if lines else ""
                pending_action["outcome"] = f"FAILED (exit={exit_code}): {tail}"
                if len(approaches) < _MAX_ATTEMPTED_APPROACHES:
                    approaches.append(pending_action)
            else:
                pending_action["outcome"] = "SUCCESS"
                if len(approaches) < _MAX_ATTEMPTED_APPROACHES:
                    approaches.append(pending_action)
            pending_action = None
        elif cls_name == "FileEditObservation" and pending_action:
            content = str(getattr(event, "content", ""))
            if "error" in content.lower() or "failed" in content.lower():
                pending_action["outcome"] = f"FAILED: {content[:150]}"
            else:
                pending_action["outcome"] = "SUCCESS"
            if len(approaches) < _MAX_ATTEMPTED_APPROACHES:
                approaches.append(pending_action)
            pending_action = None


def save_snapshot(snapshot: dict[str, Any]) -> None:
    """Persist the snapshot to disk."""
    p = _snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.debug("Pre-condensation snapshot saved: %d files, %d errors, %d decisions",
                 len(snapshot.get("files_touched", {})),
                 len(snapshot.get("recent_errors", [])),
                 len(snapshot.get("decisions", [])))


def load_snapshot() -> dict[str, Any] | None:
    """Load the most recent snapshot from disk."""
    p = _snapshot_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def format_snapshot_for_injection(snapshot: dict[str, Any]) -> str:
    """Format a snapshot into a human-readable block for LLM context injection.

    Returns a compact string suitable for appending to the post-condensation
    recovery message.
    """
    parts = ["<RESTORED_CONTEXT>"]
    parts.append(f"Events condensed: {snapshot.get('events_condensed', '?')}")

    # Files
    files = snapshot.get("files_touched", {})
    if files:
        parts.append("\nFiles touched before condensation:")
        for path, info in list(files.items())[:30]:
            parts.append(f"  {info.get('action', '?')}: {path}")

    # Recent errors
    errors = snapshot.get("recent_errors", [])
    if errors:
        parts.append(f"\nRecent errors ({len(errors)}):")
        for err in errors[-5:]:  # Show last 5
            parts.append(f"  • {err[:200]}")

    # Decisions
    decisions = snapshot.get("decisions", [])
    if decisions:
        parts.append(f"\nKey reasoning/decisions ({len(decisions)}):")
        for dec in decisions[-8:]:  # Show last 8
            parts.append(f"  • {dec[:200]}")

    # Recent commands
    commands = snapshot.get("recent_commands", [])
    if commands:
        parts.append(f"\nRecent commands ({len(commands)}):")
        for cmd_info in commands[-5:]:
            cmd = cmd_info.get("command", "")[:150]
            parts.append(f"  $ {cmd}")
            if "output" in cmd_info:
                parts.append(f"    → {cmd_info['output'][:150]}")

    # Attempted approaches — what was tried and whether it worked
    approaches = snapshot.get("attempted_approaches", [])
    if approaches:
        failed = [a for a in approaches if "FAILED" in a.get("outcome", "")]
        succeeded = [a for a in approaches if a.get("outcome") == "SUCCESS"]
        parts.append(f"\nAttempted approaches ({len(approaches)} total, {len(failed)} failed, {len(succeeded)} succeeded):")
        parts.append("FAILED approaches (DO NOT retry these):")
        for a in failed[-10:]:
            parts.append(f"  ✗ [{a.get('type', '?')}] {a.get('detail', '')[:200]}")
            parts.append(f"    → {a.get('outcome', '')[:200]}")
        if succeeded:
            parts.append("Succeeded approaches:")
            for a in succeeded[-5:]:
                parts.append(f"  ✓ [{a.get('type', '?')}] {a.get('detail', '')[:200]}")

    parts.append("</RESTORED_CONTEXT>")
    return "\n".join(parts)
