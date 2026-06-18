"""Tests for shared post-compaction artifact finalization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.context.compaction.compaction_finalizer import (
    finalize_compaction_artifacts,
)


def test_finalize_compaction_artifacts_passes_state_to_snapshot_helpers() -> None:
    state = MagicMock()
    snapshot = {'latest_directive': 'continue from canonical state'}

    with (
        patch(
            'backend.context.compaction.pre_condensation_snapshot.commit_snapshot'
        ) as commit,
        patch(
            'backend.context.compaction.pre_condensation_snapshot.load_snapshot',
            return_value=snapshot,
        ) as load,
        patch(
            'backend.context.memory.working_set.sync_snapshot_to_working_memory'
        ) as sync,
    ):
        result = finalize_compaction_artifacts(state=state)

    assert result == snapshot
    commit.assert_called_once_with(state=state)
    load.assert_called_once_with(state=state)
    sync.assert_called_once_with(snapshot, state=state)
