"""Tests for compact-boundary prompt projection."""

from __future__ import annotations

from backend.context.compactor.compact_boundary import (
    boundary_info,
    project_after_compact_boundary,
)
from backend.context.view import View
from backend.ledger.action import MessageAction
from backend.ledger.action.agent import CondensationAction


def _event(eid: int) -> MessageAction:
    event = MessageAction(content=f'msg-{eid}')
    event._id = eid
    return event


def test_project_after_boundary_inserts_summary_and_drops_pruned():
    events = [
        _event(1),
        _event(2),
        CondensationAction(
            pruned_event_ids=[2, 3],
            summary='Earlier work summarized.',
            summary_offset=1,
        ),
        _event(4),
        _event(5),
    ]
    projected = project_after_compact_boundary(events)

    assert len(projected) == 4
    assert projected[0].id == 1
    assert projected[1].content == 'Earlier work summarized.'
    assert projected[2].id == 4
    assert projected[3].id == 5


def test_boundary_info_reports_metadata():
    events = [
        _event(1),
        CondensationAction(
            pruned_event_ids=[2, 3, 4],
            summary='Summary',
            summary_offset=0,
        ),
        _event(5),
    ]
    info = boundary_info(events)

    assert info is not None
    assert info.pruned_event_count == 3
    assert info.has_summary is True
    assert info.post_boundary_event_count == len(project_after_compact_boundary(events))
    assert info.post_boundary_event_count == len(View.from_events(events).events)
