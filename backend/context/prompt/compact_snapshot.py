"""Post-compact snapshot body for the context packet."""

from __future__ import annotations

from typing import TYPE_CHECKING

COMPACT_SNAPSHOT_MARKER = '<COMPACT_SNAPSHOT>'

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


def build_compact_snapshot_body(
    state: State | None,
    events: list[Event],
) -> str:
    """Build inner compact-snapshot text for the first prompt after compaction.

    Task plan and acceptance criteria live in the per-turn ``<EXECUTION_CONTRACT>``
    section; this block only restores pre-compaction session facts.
    """
    _ = events
    if state is None:
        return ''
    try:
        from backend.context.compactor.pre_condensation_snapshot import (
            format_snapshot_body_lines,
            load_snapshot,
        )

        snapshot = load_snapshot(state=state)
    except Exception:
        return ''
    if not isinstance(snapshot, dict) or not snapshot:
        return ''
    lines = format_snapshot_body_lines(
        snapshot,
        state=state,
        include_synthesized_goal=False,
    )
    if not lines:
        return ''
    return '\n'.join(lines).strip()


__all__ = [
    'COMPACT_SNAPSHOT_MARKER',
    'build_compact_snapshot_body',
]
