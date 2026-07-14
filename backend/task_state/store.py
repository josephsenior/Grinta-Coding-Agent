"""Atomic, session-scoped persistence for the canonical task-state aggregate."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import TaskState


def _session_id() -> str | None:
    try:
        from backend.core.logging.session_event_logger import get_bound_session_id
        return get_bound_session_id()
    except Exception:
        return None


class TaskStateStore:
    def __init__(self, workspace_root: str | Path | None = None):
        from backend.core.workspace_resolution import workspace_agent_state_dir
        base = workspace_agent_state_dir(workspace_root)
        sid = _session_id()
        self.path = base / (f'task_state_{sid}.json' if sid else '.session_context_unbound/task_state.json')

    def load(self) -> TaskState:
        try:
            with self.path.open(encoding='utf-8') as handle:
                raw = json.load(handle)
            return TaskState.from_dict(raw) if isinstance(raw, dict) else TaskState()
        except (OSError, json.JSONDecodeError):
            return TaskState()

    def save(self, state: TaskState) -> None:
        from backend.persistence.file_store.atomic_write import replace_file_with_retry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=f'.{self.path.name}.', dir=self.path.parent, delete=False, mode='w', encoding='utf-8') as handle:
            tmp = Path(handle.name)
            json.dump(state.to_dict(), handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file_with_retry(tmp, self.path)
