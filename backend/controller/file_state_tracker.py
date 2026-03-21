"""File state tracking middleware for the tool pipeline.

Maintains a manifest of files read, modified, and created during a session.
The manifest survives condensation by persisting to .forge/file_manifest.json
alongside the scratchpad, and is injected into context via the planner.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.controller.tool_pipeline import ToolInvocationMiddleware
from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.observation import Observation


_MANIFEST_PATH = os.path.join(".forge", "file_manifest.json")
_MAX_TRACKED_FILES = 50


@dataclass
class FileEntry:
    path: str
    action: str  # "read", "modified", "created"
    timestamp: float = field(default_factory=time.time)


class FileStateTracker:
    """Tracks files touched during the agent session."""

    def __init__(self) -> None:
        self._files: dict[str, FileEntry] = {}

    def record(self, path: str, action: str) -> None:
        if not path:
            return
        # Upgrade action priority: created > modified > read
        existing = self._files.get(path)
        priority = {"read": 0, "modified": 1, "created": 2}
        if existing and priority.get(existing.action, 0) >= priority.get(action, 0):
            existing.timestamp = time.time()
            return
        self._files[path] = FileEntry(path=path, action=action)
        # Evict oldest if over limit
        if len(self._files) > _MAX_TRACKED_FILES:
            oldest_key = min(self._files, key=lambda k: self._files[k].timestamp)
            del self._files[oldest_key]

    def get_summary(self) -> str:
        """Return a compact summary of tracked files for injection into context."""
        if not self._files:
            return ""
        lines = ["<FILE_MANIFEST>"]
        for entry in sorted(self._files.values(), key=lambda e: e.timestamp, reverse=True):
            lines.append(f"  {entry.action}: {entry.path}")
        lines.append("</FILE_MANIFEST>")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            path: {"action": e.action, "timestamp": e.timestamp}
            for path, e in self._files.items()
        }

    def load_from_dict(self, data: dict[str, Any]) -> None:
        for path, info in data.items():
            if isinstance(info, dict):
                self._files[path] = FileEntry(
                    path=path,
                    action=info.get("action", "read"),
                    timestamp=info.get("timestamp", 0),
                )


class FileStateMiddleware(ToolInvocationMiddleware):
    """Observe-stage middleware that records file operations to the tracker."""

    def __init__(self) -> None:
        self._tracker = FileStateTracker()

    @property
    def tracker(self) -> FileStateTracker:
        return self._tracker

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        action = ctx.action
        action_cls = type(action).__name__

        try:
            if action_cls == "FileEditAction":
                path = getattr(action, "path", "")
                command = getattr(action, "command", "")
                if command == "create_file":
                    self._tracker.record(path, "created")
                elif command == "view_file":
                    self._tracker.record(path, "read")
                else:
                    self._tracker.record(path, "modified")
            elif action_cls == "FileReadAction":
                path = getattr(action, "path", "")
                self._tracker.record(path, "read")
            elif action_cls == "FileWriteAction":
                path = getattr(action, "path", "")
                self._tracker.record(path, "created")
        except Exception:
            logger.debug("FileStateMiddleware: failed to record action", exc_info=True)
