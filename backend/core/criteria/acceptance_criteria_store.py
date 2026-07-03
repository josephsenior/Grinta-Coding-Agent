"""Workspace-backed persistence for flat acceptance criteria."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from backend.core.criteria.criterion_item import normalize_criteria_list

_SAVE_LOCKS: dict[str, threading.Lock] = {}
_SAVE_LOCKS_GUARD = threading.Lock()


def _save_lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _SAVE_LOCKS_GUARD:
        lock = _SAVE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SAVE_LOCKS[key] = lock
        return lock


class AcceptanceCriteriaStore:
    """Manage the persisted acceptance criteria list under the workspace agent state dir."""

    def __init__(self, workspace_root: str | Path | None = None):
        if workspace_root is None:
            from backend.core.workspace_resolution import (
                require_effective_workspace_root,
            )

            workspace_root = require_effective_workspace_root()
        from backend.core.workspace_resolution import workspace_agent_state_dir

        self.path = workspace_agent_state_dir(workspace_root) / 'acceptance_criteria.json'

    def load_from_file(self) -> list[dict[str, Any]]:
        """Load criteria from disk."""
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        try:
            return normalize_criteria_list(data)
        except TypeError:
            return []

    def save_to_file(self, criteria_list: list[dict[str, Any]]) -> None:
        """Save criteria to disk atomically."""
        from backend.persistence.file_store.atomic_write import replace_file_with_retry

        normalized = normalize_criteria_list(criteria_list)
        with _save_lock_for(self.path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            dir_name = str(self.path.parent)
            with tempfile.NamedTemporaryFile(
                prefix=f'.{self.path.name}.tmp.',
                dir=dir_name,
                delete=False,
                mode='w',
                encoding='utf-8',
            ) as f:
                tmp_path = Path(f.name)
                json.dump(normalized, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                replace_file_with_retry(tmp_path, self.path)
            except Exception:
                with suppress(OSError):
                    tmp_path.unlink(missing_ok=True)
                raise

    def append_to_file(self, new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append normalized items and persist."""
        merged = self.load_from_file() + normalize_criteria_list(new_items)
        self.save_to_file(merged)
        return merged


__all__ = ['AcceptanceCriteriaStore']
