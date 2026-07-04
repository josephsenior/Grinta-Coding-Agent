"""Workspace-backed task plan persistence utilities."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from backend.core.tasks.task_status import (
    TASK_STATUS_BLOCKED,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_SKIPPED,
    TASK_STATUS_TODO,
)

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


class TaskTracker:
    """Manage session-scoped task plan JSON under the workspace agent state dir."""

    def __init__(self, workspace_root: str | Path | None = None):
        """Initialize the task tracker with an optional explicit workspace root."""
        if workspace_root is None:
            from backend.context.memory.session_context import scoped_agent_path

            self.path = scoped_agent_path('active_plan', '.json')
            return
        from backend.context.memory.session_context import resolve_session_id
        from backend.core.workspace_resolution import workspace_agent_state_dir

        base = workspace_agent_state_dir(workspace_root)
        sid = resolve_session_id()
        if sid:
            self.path = base / f'active_plan_{sid}.json'
        else:
            self.path = base / 'active_plan.json'

    def load_from_file(self) -> list[dict[str, Any]]:
        """Load the task list from disk."""
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        if not isinstance(data, list):
            return []

        from backend.core.tasks.plan_step import normalize_plan_step_payload

        try:
            return [
                normalize_plan_step_payload(task, i + 1) for i, task in enumerate(data)
            ]
        except TypeError:
            return []

    def save_to_file(self, task_list: list[dict[str, Any]]) -> None:
        """Save the task list to disk atomically."""
        from backend.core.tasks.plan_step import normalize_plan_step_payload
        from backend.persistence.file_store.atomic_write import replace_file_with_retry

        normalized = [
            normalize_plan_step_payload(task, i + 1) for i, task in enumerate(task_list)
        ]
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

    def update_task_status(
        self, task_id: str, status: str, result: str | None = None
    ) -> tuple[bool, str]:
        """Update status of a single task by ID."""
        valid_statuses = {
            TASK_STATUS_TODO,
            TASK_STATUS_IN_PROGRESS,
            TASK_STATUS_DONE,
            TASK_STATUS_SKIPPED,
            TASK_STATUS_BLOCKED,
        }
        if status not in valid_statuses:
            return (
                False,
                f"Invalid status '{status}'. Valid: {', '.join(sorted(valid_statuses))}",
            )

        task_list = self.load_from_file()
        if not task_list:
            return False, 'No tasks found. Create a plan first with update command.'

        task = _find_task_by_id(task_list, task_id)
        if task is None:
            return False, f"Task '{task_id}' not found."

        old_status = task.get('status', 'unknown')
        task['status'] = status
        if result is not None:
            task['result'] = result
        self.save_to_file(task_list)
        return True, f"Task '{task_id}' status updated: {old_status} -> {status}"


def _find_task_by_id(
    task_list: list[dict[str, Any]], task_id: str
) -> dict[str, Any] | None:
    """Find a task by ID in the task list, including nested subtasks."""
    for task in task_list:
        if task.get('id') == task_id:
            return task
        subtasks = task.get('subtasks', [])
        if subtasks:
            found = _find_task_by_id(subtasks, task_id)
            if found is not None:
                return found
    return None


__all__ = ['TaskTracker']
