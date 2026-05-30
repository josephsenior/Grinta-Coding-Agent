"""File state tracking middleware for the tool pipeline.

Maintains a manifest of files read, modified, and created during a session.
The manifest path for on-disk persistence (when used) is under
``~/.grinta/workspaces/<id>/agent/file_manifest.json``; the in-memory summary
is injected into context via the planner.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
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


def _normalize_path_key(path_str: str) -> str | None:
    """Stable dict key for a resolved filesystem path."""
    try:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        resolved = p.resolve()
        s = os.path.normpath(str(resolved))
        if OS_CAPS.is_windows:
            s = os.path.normcase(s)
        return s
    except OSError:
        return None


class FileStateTracker:
    """Tracks files touched during the agent session."""

    def __init__(self) -> None:
        self._files: dict[str, FileEntry] = {}

    def record(self, path: str, action: str) -> None:
        if not path:
            return
        existing = self._files.get(path)
        priority = {'read': 0, 'modified': 1, 'created': 2}
        if existing and priority.get(existing.action, 0) >= priority.get(action, 0):
            existing.timestamp = time.time()
            return
        self._files[path] = FileEntry(path=path, action=action)
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


_MUTATING_EDIT_COMMANDS: frozenset[str] = frozenset(
    {
        'insert_text',
        'edit',
        'write',
        'str_replace',
        'replace_string',
        'create_file',
    }
)

# ---------------------------------------------------------------------------
# Non-LSP blast-radius helpers
# ---------------------------------------------------------------------------

# Matches diff lines that remove a top-level (or inner) class/def name:
# "-def foo(" or "-class Bar:" with optional leading whitespace.
_REMOVED_SYMBOL_RE = re.compile(
    r'^-[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+(\w+)',
    re.MULTILINE,
)


def _extract_removed_symbols(diff: str) -> list[str]:
    """Return deduplicated list of Python symbol names removed in *diff*."""
    return list(dict.fromkeys(_REMOVED_SYMBOL_RE.findall(diff)))


def _find_symbol_references(
    symbols: list[str],
    session_files: list[str],
    exclude_path: str,
    *,
    max_lines_per_file: int = 3,
    max_files: int = 6,
) -> str:
    """Plain-text search across *session_files* for references to *symbols*.

    Returns a compact multi-line string suitable for appending to an
    observation.  Bounded output: at most *max_files* files, at most
    *max_lines_per_file* matching lines each.
    """
    if not symbols or not session_files:
        return ''

    try:
        norm_exclude = str(Path(exclude_path).resolve())
    except Exception:
        norm_exclude = exclude_path

    report: list[str] = []
    files_reported = 0
    for filepath in session_files:
        if files_reported >= max_files:
            break
        try:
            norm_fp = str(Path(filepath).resolve())
        except Exception:
            norm_fp = filepath
        if norm_fp == norm_exclude:
            continue
        try:
            text = Path(filepath).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        file_lines: list[str] = []
        for sym in symbols:
            if sym not in text:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if sym in line and stripped and not stripped.startswith('#'):
                    file_lines.append(f'  {filepath}:{lineno}: {stripped[:100]}')
                    if len(file_lines) >= max_lines_per_file:
                        break
            if len(file_lines) >= max_lines_per_file:
                break
        if file_lines:
            report.extend(file_lines)
            files_reported += 1
    return '\n'.join(report)


class FileStateMiddleware(ToolInvocationMiddleware):
    """Middleware that records file operations."""

    def __init__(self) -> None:
        self._tracker = FileStateTracker()

    @property
    def tracker(self) -> FileStateTracker:
        return self._tracker

    async def execute(self, ctx: ToolInvocationContext) -> None:
        pass

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        action = ctx.action
        action_cls = type(action).__name__
        mutated_path: str = ''
        observation_failed = False

        if observation is None:
            return

        try:
            from backend.ledger.observation import ErrorObservation

            observation_failed = isinstance(observation, ErrorObservation)
        except Exception:
            observation_failed = False

        try:
            if action_cls == 'FileEditAction':
                path = getattr(action, 'path', '')
                command = getattr(action, 'command', '') or 'write'
                if observation_failed:
                    return
                if command == 'create_file':
                    self._tracker.record(path, 'created')
                    mutated_path = path
                elif command == 'read_file':
                    self._tracker.record(path, 'read')
                else:
                    self._tracker.record(path, 'modified')
                    mutated_path = path
            elif action_cls == 'FileReadAction':
                if observation_failed:
                    return
                path = getattr(action, 'path', '')
                self._tracker.record(path, 'read')
            elif action_cls == 'FileWriteAction':
                if observation_failed:
                    return
                path = getattr(action, 'path', '')
                self._tracker.record(path, 'created')
                mutated_path = path
        except Exception:
            logger.debug('FileStateMiddleware: failed to record action', exc_info=True)

        # Blast radius: when symbols are removed/renamed, report session files
        # that still reference them so the agent knows what else needs fixing.
        if mutated_path and observation is not None:
            try:
                diff = (
                    ctx.metadata.get('pre_exec_diff', '')
                    if hasattr(ctx, 'metadata') and isinstance(ctx.metadata, dict)
                    else ''
                )
                if diff:
                    symbols = _extract_removed_symbols(diff)
                    if symbols:
                        session_files = [e.path for e in self._tracker._files.values()]
                        refs = _find_symbol_references(
                            symbols, session_files, exclude_path=mutated_path
                        )
                        if refs:
                            content = getattr(observation, 'content', None)
                            if isinstance(content, str):
                                observation.content = (
                                    content
                                    + '\n\n<BLAST_RADIUS>\n'
                                    + 'Symbols removed/renamed: '
                                    + ', '.join(symbols)
                                    + '\nSession files that reference them:\n'
                                    + refs
                                    + '\n'
                                    + '</BLAST_RADIUS>'
                                )
            except Exception:
                logger.debug(
                    'FileStateMiddleware: blast radius check failed', exc_info=True
                )
