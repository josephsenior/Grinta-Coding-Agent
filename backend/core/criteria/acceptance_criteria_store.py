"""Workspace-backed persistence for flat acceptance criteria."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from backend.core.criteria.criterion_item import (
    backfill_criterion_ids,
    normalize_criteria_list,
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


class AcceptanceCriteriaStore:
    """Manage session-scoped acceptance criteria JSON under the workspace agent dir."""

    def __init__(self, workspace_root: str | Path | None = None):
        if workspace_root is None:
            from backend.context.memory.session_context import scoped_agent_path

            self.path = scoped_agent_path('acceptance_criteria', '.json')
            return
        from backend.context.memory.session_context import resolve_session_id
        from backend.core.workspace_resolution import workspace_agent_state_dir

        base = workspace_agent_state_dir(workspace_root)
        sid = resolve_session_id()
        if sid:
            self.path = base / f'acceptance_criteria_{sid}.json'
        else:
            self.path = base / 'acceptance_criteria.json'

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
            return backfill_criterion_ids(normalize_criteria_list(data))
        except TypeError:
            return []

    def save_to_file(self, criteria_list: list[dict[str, Any]]) -> None:
        """Save criteria to disk atomically."""
        from backend.persistence.file_store.atomic_write import replace_file_with_retry

        normalized = backfill_criterion_ids(normalize_criteria_list(criteria_list))
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
        from backend.core.criteria.criterion_item import assign_criterion_ids

        existing = self.load_from_file()
        appended = assign_criterion_ids(
            normalize_criteria_list(new_items),
            existing=existing,
        )
        merged = existing + appended
        self.save_to_file(merged)
        return merged

    def refine_criterion(
        self,
        criterion_id: str,
        *,
        new_assertion: str,
        reason: str,
        changed_at: str,
        persist: bool = True,
    ) -> list[dict[str, Any]]:
        """Update one criterion assertion and append to its change log."""
        updated = build_refined_criteria_list(
            self.load_from_file(),
            criterion_id=criterion_id,
            new_assertion=new_assertion,
            reason=reason,
            changed_at=changed_at,
        )
        if persist:
            self.save_to_file(updated)
        return updated

    def render_for_prompt_lines(
        self,
        *,
        max_items: int = 10,
        header: str = '- Acceptance gates:',
        show_empty: bool = False,
    ) -> list[str]:
        """Render acceptance criteria as prompt lines."""
        from backend.context.render.task_context import render_acceptance_gates

        return render_acceptance_gates(
            self.load_from_file(),
            max_items=max_items,
            header=header,
            show_empty=show_empty,
        )


def build_refined_criteria_list(
    existing: list[dict[str, Any]],
    *,
    criterion_id: str,
    new_assertion: str,
    reason: str,
    changed_at: str,
) -> list[dict[str, Any]]:
    """Return criteria list with one refined assertion and appended change log."""
    target_id = str(criterion_id or '').strip()
    new_text = str(new_assertion or '').strip()
    change_reason = str(reason or '').strip()
    if not target_id:
        raise ValueError('criterion_id is required')
    if not new_text:
        raise ValueError('new_assertion is required')
    if not change_reason:
        raise ValueError('reason is required')

    found = False
    updated: list[dict[str, Any]] = []
    for item in existing:
        if str(item.get('id') or '').strip() != target_id:
            updated.append(dict(item))
            continue
        found = True
        row = dict(item)
        old_assertion = str(row.get('assertion') or '').strip()
        changes = list(row.get('changes') or [])
        changes.append(
            {
                'at': changed_at,
                'old_assertion': old_assertion,
                'new_assertion': new_text,
                'reason': change_reason,
            }
        )
        row['assertion'] = new_text
        row['changes'] = changes
        updated.append(row)

    if not found:
        raise KeyError(f'Criterion {target_id!r} not found')

    return updated


__all__ = ['AcceptanceCriteriaStore', 'build_refined_criteria_list']
