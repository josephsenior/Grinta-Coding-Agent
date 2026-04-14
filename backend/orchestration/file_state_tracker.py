"""File state tracking middleware for the tool pipeline.

Maintains a manifest of files read, modified, and created during a session.
The manifest path for on-disk persistence (when used) is under
``~/.grinta/workspaces/<id>/agent/file_manifest.json``; the in-memory summary
is injected into context via the planner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.tool_pipeline import ToolInvocationContext


def file_manifest_path() -> Path:
    """Resolved path for the session file manifest (agent state bucket)."""
    from backend.core.workspace_resolution import workspace_agent_state_dir

    return workspace_agent_state_dir() / 'file_manifest.json'


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
        priority = {'read': 0, 'modified': 1, 'created': 2}
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
            return ''
        lines = ['<FILE_MANIFEST>']
        for entry in sorted(
            self._files.values(), key=lambda e: e.timestamp, reverse=True
        ):
            lines.append(f'  {entry.action}: {entry.path}')
        lines.append('</FILE_MANIFEST>')
        return '\n'.join(lines)

    def has_been_read_recently(self, path: str) -> bool:
        entry = self._files.get(path)
        return entry is not None and entry.action in ('read', 'modified', 'created')

    def has_been_modified_recently(self, path: str) -> bool:
        entry = self._files.get(path)
        return entry is not None and entry.action in ('modified', 'created')

    def to_dict(self) -> dict[str, Any]:
        return {
            path: {'action': e.action, 'timestamp': e.timestamp}
            for path, e in self._files.items()
        }

    def load_from_dict(self, data: dict[str, Any]) -> None:
        for path, info in data.items():
            if isinstance(info, dict):
                self._files[path] = FileEntry(
                    path=path,
                    action=info.get('action', 'read'),
                    timestamp=info.get('timestamp', 0),
                )


class FileStateMiddleware(ToolInvocationMiddleware):
    """Middleware that blocks unknown file edits and records file operations."""

    def __init__(self) -> None:
        self._tracker = FileStateTracker()

    @property
    def tracker(self) -> FileStateTracker:
        return self._tracker

    async def execute(self, ctx: ToolInvocationContext) -> None:
        action = ctx.action
        action_cls = type(action).__name__

        # Enforce read-before-edit for apply_patch and related file modifications
        requires_read_check = False
        target_path = ''

        if action_cls == 'FileEditAction':
            command = getattr(action, 'command', '')
            if command == 'apply_patch':
                requires_read_check = True
                # Usually apply_patch targets the path arg
                target_path = getattr(action, 'path', '')

        if requires_read_check and target_path:
            is_known = self._tracker.has_been_read_recently(
                target_path
            ) or self._tracker.has_been_modified_recently(target_path)
            # If never seen recently, block the invocation
            if not is_known:
                ctx.block(
                    f'[FILE_STATE_GUARD] Cannot edit {target_path}. You must run view_file/read_file on it '
                    f'before applying a patch to ensure you have the exact correct context.'
                )

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        action = ctx.action
        action_cls = type(action).__name__

        try:
            if action_cls == 'FileEditAction':
                path = getattr(action, 'path', '')
                command = getattr(action, 'command', '')
                if command == 'create_file':
                    self._tracker.record(path, 'created')
                elif command == 'view_file':
                    self._tracker.record(path, 'read')
                else:
                    self._tracker.record(path, 'modified')
            elif action_cls == 'FileReadAction':
                path = getattr(action, 'path', '')
                self._tracker.record(path, 'read')
            elif action_cls == 'FileWriteAction':
                path = getattr(action, 'path', '')
                self._tracker.record(path, 'created')
        except Exception:
            logger.debug('FileStateMiddleware: failed to record action', exc_info=True)
