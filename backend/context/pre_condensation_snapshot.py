"""Pre-condensation snapshot — auto-extracts critical context before condensation.

When condensation fires, the LLM loses all tool outputs and file contents.
This module extracts the most important context from the about-to-be-pruned
events and persists it to ``.app/pre_condensation_snapshot.json``.

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

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.event import Event

_WORKSPACE_ROOT = os.environ.get("APP_WORKSPACE_DIR", ".")
_SNAPSHOT_FILE = ".app/pre_condensation_snapshot.json"

# Limits to prevent the snapshot from becoming too large
_MAX_ERRORS = 10
_MAX_DECISIONS = 15
_MAX_COMMANDS = 10
_MAX_CONTENT_LENGTH = 500


def _snapshot_path() -> Path:
    return Path(_WORKSPACE_ROOT) / _SNAPSHOT_FILE


_MAX_ATTEMPTED_APPROACHES = 20


def _file_edit_observation_indicates_failure(content: str) -> bool:
    """True only for known failure shapes; avoids treating diff/code containing 'error' as failure."""
    s = content.strip()
    low = s.lower()
    if low.startswith("skipped:"):
        return True
    if "[edit error:" in low:
        return True
    if s.startswith("ERROR:"):
        return True
    if "critical verification failure" in low:
        return True
    return False


def extract_snapshot(events: list[Event]) -> dict[str, Any]:
    """Extract critical context from events that are about to be condensed.

    Args:
        events: The events that will be pruned during condensation.

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


def _extract_edit_file_info(event: Event, files: dict) -> None:
    """Extract file path from FileEdit* events."""
    path = getattr(event, "path", "")
    if path:
        command = getattr(event, "command", "edit")
        files[path] = {"action": command, "type": "edit"}


def _extract_read_file_info(event: Event, files: dict) -> None:
    """Extract file path from FileRead* events."""
    path = getattr(event, "path", "")
    if path and path not in files:
        files[path] = {"action": "read", "type": "read"}


def _extract_cmd_run_file_paths(event: Event, files: dict) -> None:
    """Extract file paths from CmdRunAction (cat/head/tail)."""
    cmd = getattr(event, "command", "")
    if "cat " not in cmd and "head " not in cmd and "tail " not in cmd:
        return
    parts = cmd.split()
    for i, part in enumerate(parts):
        if part in ("cat", "head", "tail") and i + 1 < len(parts):
            path = parts[i + 1].strip("'\"")
            if path and path not in files:
                files[path] = {"action": "read_via_cmd", "type": "read"}


def _extract_file_info(event: Event, snapshot: dict) -> None:
    """Extract file paths and actions from file-related events."""
    cls_name = type(event).__name__
    files = snapshot["files_touched"]

    if cls_name in ("FileEditAction", "FileEditObservation"):
        _extract_edit_file_info(event, files)
    elif cls_name in ("FileReadAction", "FileReadObservation"):
        _extract_read_file_info(event, files)
    elif cls_name == "CmdRunAction":
        _extract_cmd_run_file_paths(event, files)


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
        pending_action = _process_event_for_approaches(event, approaches, pending_action)


def _process_event_for_approaches(
    event: Event,
    approaches: list,
    pending: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Process one event for attempted-approaches extraction.

    Dispatches on event type: FileEditAction/CmdRunAction start a pending action;
    ErrorObservation/CmdOutputObservation/FileEditObservation resolve it and append
    to approaches. Returns the new pending action (or None if resolved).
    """
    cls_name = type(event).__name__
    if cls_name == "FileEditAction":
        return _make_file_edit_action(event)
    if cls_name == "CmdRunAction":
        return _make_cmd_run_action(event)
    if cls_name == "ErrorObservation" and pending:
        _append_with_outcome(approaches, pending, f"FAILED: {str(getattr(event, 'content', ''))[:150]}")
        return None
    if cls_name == "CmdOutputObservation" and pending:
        _handle_cmd_output(approaches, pending, event)
        return None
    if cls_name == "FileEditObservation" and pending:
        _handle_file_edit_observation(approaches, pending, event)
        return None
    return pending


def _make_file_edit_action(event: Event) -> dict[str, Any]:
    """Build a file_edit pending action dict from a FileEditAction event."""
    path = getattr(event, "path", "")
    command = getattr(event, "command", "edit")
    old_str = str(getattr(event, "old_str", ""))[:80] if hasattr(event, "old_str") else ""
    detail = f"{command} on {path}"
    if old_str:
        detail += f" (old_str: {old_str!r}...)"
    return {"type": "file_edit", "detail": detail}


def _make_cmd_run_action(event: Event) -> dict[str, Any]:
    """Build a command pending action dict from a CmdRunAction event."""
    cmd = str(getattr(event, "command", ""))[:150]
    return {"type": "command", "detail": cmd}


def _append_with_outcome(approaches: list, action: dict, outcome: str) -> None:
    """Append action with outcome to approaches if under the max limit."""
    if len(approaches) < _MAX_ATTEMPTED_APPROACHES:
        action["outcome"] = outcome
        approaches.append(action)


def _handle_cmd_output(
    approaches: list, pending: dict[str, Any], event: Event
) -> dict[str, Any] | None:
    """Resolve pending action with CmdOutputObservation result (SUCCESS or FAILED)."""
    exit_code = getattr(event, "exit_code", 0)
    if exit_code != 0:
        content = str(getattr(event, "content", ""))
        lines = content.strip().split("\n")
        tail = lines[-1][:150] if lines else ""
        outcome = f"FAILED (exit={exit_code}): {tail}"
    else:
        outcome = "SUCCESS"
    _append_with_outcome(approaches, pending, outcome)
    return None


def _handle_file_edit_observation(
    approaches: list, pending: dict[str, Any], event: Event
) -> dict[str, Any] | None:
    """Resolve pending action with FileEditObservation result (SUCCESS or FAILED)."""
    content = str(getattr(event, "content", ""))
    failed = _file_edit_observation_indicates_failure(content)
    outcome = f"FAILED: {content[:150]}" if failed else "SUCCESS"
    _append_with_outcome(approaches, pending, outcome)
    return None


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
    parts.extend(_format_files_section(snapshot.get("files_touched", {})))
    parts.extend(_format_errors_section(snapshot.get("recent_errors", [])))
    parts.extend(_format_decisions_section(snapshot.get("decisions", [])))
    parts.extend(_format_commands_section(snapshot.get("recent_commands", [])))
    parts.extend(_format_approaches_section(snapshot.get("attempted_approaches", [])))
    parts.append("</RESTORED_CONTEXT>")
    return "\n".join(parts)


def _format_files_section(files: dict) -> list[str]:
    """Format files touched section."""
    if not files:
        return []
    lines = ["\nFiles touched before condensation:"]
    for path, info in list(files.items())[:30]:
        lines.append(f"  {info.get('action', '?')}: {path}")
    return lines


def _format_errors_section(errors: list) -> list[str]:
    """Format recent errors section."""
    if not errors:
        return []
    lines = [f"\nRecent errors ({len(errors)}):"]
    for err in errors[-5:]:
        lines.append(f"  • {err[:200]}")
    return lines


def _format_decisions_section(decisions: list) -> list[str]:
    """Format key reasoning/decisions section."""
    if not decisions:
        return []
    lines = [f"\nKey reasoning/decisions ({len(decisions)}):"]
    for dec in decisions[-8:]:
        lines.append(f"  • {dec[:200]}")
    return lines


def _format_commands_section(commands: list) -> list[str]:
    """Format recent commands section."""
    if not commands:
        return []
    lines = [f"\nRecent commands ({len(commands)}):"]
    for cmd_info in commands[-5:]:
        cmd = cmd_info.get("command", "")[:150]
        lines.append(f"  $ {cmd}")
        if "output" in cmd_info:
            lines.append(f"    → {cmd_info['output'][:150]}")
    return lines


def _format_approaches_section(approaches: list) -> list[str]:
    """Format attempted approaches (failed/succeeded) section."""
    if not approaches:
        return []
    failed = [a for a in approaches if "FAILED" in a.get("outcome", "")]
    succeeded = [a for a in approaches if a.get("outcome") == "SUCCESS"]
    lines = [
        f"\nAttempted approaches ({len(approaches)} total, {len(failed)} failed, {len(succeeded)} succeeded):",
        "FAILED approaches (DO NOT retry these):",
    ]
    for a in failed[-10:]:
        lines.append(f"  ✗ [{a.get('type', '?')}] {a.get('detail', '')[:200]}")
        lines.append(f"    → {a.get('outcome', '')[:200]}")
    if succeeded:
        lines.append("Succeeded approaches:")
        for a in succeeded[-5:]:
            lines.append(f"  ✓ [{a.get('type', '?')}] {a.get('detail', '')[:200]}")
    return lines
