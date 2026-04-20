"""File state tracking middleware for the tool pipeline.

Maintains a manifest of files read, modified, and created during a session.
The manifest path for on-disk persistence (when used) is under
``~/.grinta/workspaces/<id>/agent/file_manifest.json``; the in-memory summary
is injected into context via the planner.

Read snapshots (mtime + content hash) support Claude-style staleness detection:
if disk changes after a read, edits can be blocked until the model re-reads.
"""

from __future__ import annotations

import hashlib
import os
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


@dataclass(frozen=True)
class ReadSnapshot:
    """Disk state observed after a read (Claude-style readFileState + mtime)."""

    mtime: float
    content_sha256: str


def _normalize_path_key(path_str: str) -> str | None:
    """Stable dict key for a resolved filesystem path."""
    try:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        resolved = p.resolve()
        s = os.path.normpath(str(resolved))
        if os.name == 'nt':
            s = os.path.normcase(s)
        return s
    except OSError:
        return None


class FileStateTracker:
    """Tracks files touched during the agent session."""

    def __init__(self) -> None:
        self._files: dict[str, FileEntry] = {}
        self._read_snapshots: dict[str, ReadSnapshot] = {}

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
            self._read_snapshots.pop(oldest_key, None)

    def record_read_snapshot_from_disk(self, path_str: str) -> None:
        """Store mtime + sha256 of file bytes after a read (for staleness checks)."""
        key = _normalize_path_key(path_str)
        if not key:
            return
        try:
            p = Path(key)
            if not p.is_file():
                return
            st = p.stat()
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            self._read_snapshots[key] = ReadSnapshot(
                mtime=st.st_mtime,
                content_sha256=digest,
            )
        except OSError:
            logger.debug('record_read_snapshot_from_disk failed for %s', path_str)

    def invalidate_read_snapshot(self, path_str: str) -> None:
        key = _normalize_path_key(path_str)
        if key:
            self._read_snapshots.pop(key, None)

    def check_read_stale(self, path_str: str) -> str | None:
        """Return error message if disk changed since snapshot; else None.

        If mtime is newer but bytes hash matches (e.g. Windows noise), allow.
        """
        if os.environ.get('GRINTA_SKIP_READ_STALE_CHECK', '').lower() in (
            '1',
            'true',
            'yes',
        ):
            return None
        key = _normalize_path_key(path_str)
        if not key:
            return None
        snap = self._read_snapshots.get(key)
        if snap is None:
            return None
        try:
            p = Path(key)
            if not p.is_file():
                return None
            st = p.stat()
            if st.st_mtime <= snap.mtime:
                return None
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            if digest == snap.content_sha256:
                return None
        except OSError:
            return None
        return (
            f'[FILE_STATE_GUARD] File changed on disk since it was read '
            f'(path {path_str!r}). Read it again before editing.'
        )

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


_READ_BEFORE_EDIT_COMMANDS: frozenset[str] = frozenset(
    {
        'apply_patch',
        'replace_text',
        'insert_text',
        'edit',
        'str_replace',
    }
)

_MUTATING_EDIT_COMMANDS: frozenset[str] = frozenset(
    {
        'replace_text',
        'insert_text',
        'edit',
        'write',
        'str_replace',
        'apply_patch',
    }
)


def _read_before_edit_enforced() -> bool:
    """Read-before-edit is on by default; opt out with GRINTA_SKIP_READ_BEFORE_EDIT=1.

    Claude Code enforces this unconditionally and it is their single most
    effective guard against "string not found" / context drift errors. We
    allow opt-out for legacy replay scenarios and power users.
    """
    return os.environ.get('GRINTA_SKIP_READ_BEFORE_EDIT', '').lower() not in (
        '1',
        'true',
        'yes',
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
        mutating_edit = False

        if action_cls == 'FileEditAction':
            command = getattr(action, 'command', '') or 'write'
            if command in _READ_BEFORE_EDIT_COMMANDS and _read_before_edit_enforced():
                requires_read_check = True
                target_path = getattr(action, 'path', '')
            if command in _MUTATING_EDIT_COMMANDS:
                mutating_edit = True
                target_path = target_path or getattr(action, 'path', '')

        if requires_read_check and target_path:
            is_known = self._tracker.has_been_read_recently(
                target_path
            ) or self._tracker.has_been_modified_recently(target_path)
            # Skip the read-before-edit guard when the file does not yet
            # exist — this is a common pattern for "create-then-edit" flows
            # where the first edit supplies the initial body. ``create_file``
            # is already excluded by command allowlist above.
            if not is_known:
                try:
                    exists = Path(target_path).expanduser().is_file()
                except OSError:
                    exists = True
                if not exists:
                    return
                ctx.block(
                    '[FILE_STATE_GUARD] File has not been read yet in this '
                    f'session: {target_path}. Read it first (use view_file or '
                    'grep to locate the exact text) before editing, otherwise '
                    'your old_str / anchor context will likely not match.'
                )

        if (
            not ctx.blocked
            and mutating_edit
            and target_path
            and action_cls == 'FileEditAction'
        ):
            stale_msg = self._tracker.check_read_stale(target_path)
            if stale_msg:
                ctx.block(stale_msg)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        action = ctx.action
        action_cls = type(action).__name__

        try:
            if action_cls == 'FileEditAction':
                path = getattr(action, 'path', '')
                command = getattr(action, 'command', '') or 'write'
                if command == 'create_file':
                    self._tracker.record(path, 'created')
                elif command == 'view_file':
                    self._tracker.record(path, 'read')
                    self._tracker.record_read_snapshot_from_disk(path)
                else:
                    self._tracker.record(path, 'modified')
                    self._tracker.invalidate_read_snapshot(path)
            elif action_cls == 'FileReadAction':
                path = getattr(action, 'path', '')
                self._tracker.record(path, 'read')
                self._tracker.record_read_snapshot_from_disk(path)
            elif action_cls == 'FileWriteAction':
                path = getattr(action, 'path', '')
                self._tracker.record(path, 'created')
                self._tracker.invalidate_read_snapshot(path)
        except Exception:
            logger.debug('FileStateMiddleware: failed to record action', exc_info=True)
