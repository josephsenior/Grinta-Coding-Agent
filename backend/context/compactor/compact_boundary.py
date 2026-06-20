"""Compact-boundary projection for LLM-facing context.

A compaction boundary is not amnesia: the full ledger stays intact for the
UI and audit trail.  The boundary only defines where the *prompt prefix*
starts — summary plus events after the last ``CondensationAction``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context.view import View
from backend.ledger.action.agent import CondensationAction

if TYPE_CHECKING:
    from backend.ledger.event import Event


@dataclass(frozen=True)
class CompactBoundaryInfo:
    """Metadata about the active compaction boundary."""

    boundary_event_id: int
    pruned_event_count: int
    has_summary: bool
    post_boundary_event_count: int


def find_last_condensation_action(events: list[Event]) -> CondensationAction | None:
    """Return the most recent condensation action in *events*."""
    for event in reversed(events):
        if isinstance(event, CondensationAction):
            return event
    return None


def project_after_compact_boundary(events: list[Event]) -> list[Event]:
    """Return the LLM-facing event list anchored at the last compaction boundary."""
    if not events:
        return []
    return list(View.from_events(events).events)


def boundary_info(events: list[Event]) -> CompactBoundaryInfo | None:
    """Describe the active boundary, if any."""
    action = find_last_condensation_action(events)
    if action is None:
        return None
    projected = project_after_compact_boundary(events)
    return CompactBoundaryInfo(
        boundary_event_id=action.id,
        pruned_event_count=len(action.pruned),
        has_summary=bool(action.summary),
        post_boundary_event_count=len(projected),
    )


__all__ = [
    'CompactBoundaryInfo',
    'boundary_info',
    'find_last_condensation_action',
    'project_after_compact_boundary',
]
