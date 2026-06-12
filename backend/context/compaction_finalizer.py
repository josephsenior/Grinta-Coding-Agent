"""Shared post-compaction artifact finalization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


def finalize_compaction_artifacts(*, state: State) -> dict[str, Any] | None:
    """Commit staged compaction artifacts and sync session-scoped memory."""
    try:
        from backend.context.pre_condensation_snapshot import (
            commit_snapshot,
            load_snapshot,
        )
        from backend.context.working_set import sync_snapshot_to_working_memory

        commit_snapshot(state=state)
        snapshot = load_snapshot(state=state)
        sync_snapshot_to_working_memory(snapshot, state=state)
        return snapshot if isinstance(snapshot, dict) else None
    except Exception:
        logger.debug('Post-compaction artifact finalization failed', exc_info=True)
        return None


__all__ = ['finalize_compaction_artifacts']
