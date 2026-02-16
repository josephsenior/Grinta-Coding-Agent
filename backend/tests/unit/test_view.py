"""Tests for backend.memory.view — View container."""

from __future__ import annotations

import pytest

from backend.events.action import AgentThinkAction, MessageAction
from backend.events.action.agent import CondensationAction, CondensationRequestAction
from backend.events.observation.agent import AgentCondensationObservation
from backend.memory.view import View


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(eid: int = 0):
    """Build a real Event with a specific id."""
    e = MessageAction(content=f"msg-{eid}")
    e._id = eid
    return e


# ===================================================================
# Basic container protocol
# ===================================================================

class TestViewContainer:

    def test_len(self):
        v = View(events=[_event(1), _event(2)])
        assert len(v) == 2

    def test_len_empty(self):
        v = View(events=[])
        assert len(v) == 0

    def test_iter(self):
        evts = [_event(1), _event(2), _event(3)]
        v = View(events=evts)
        result = list(v)
        assert len(result) == 3

    def test_getitem_int(self):
        evts = [_event(10), _event(20)]
        v = View(events=evts)
        assert v[0].id == 10
        assert v[1].id == 20

    def test_getitem_negative_index(self):
        evts = [_event(1), _event(2), _event(3)]
        v = View(events=evts)
        assert v[-1].id == 3

    def test_getitem_slice(self):
        evts = [_event(i) for i in range(5)]
        v = View(events=evts)
        sliced = v[1:3]
        assert len(sliced) == 2
        assert sliced[0].id == 1
        assert sliced[1].id == 2

    def test_getitem_invalid_type_raises(self):
        v = View(events=[_event(0)])
        with pytest.raises(TypeError, match="Invalid key type"):
            v["bad"]

    def test_getitem_out_of_bounds_raises(self):
        v = View(events=[_event(0)])
        with pytest.raises(IndexError):
            v[5]


# ===================================================================
# _collect_forgotten_event_ids
# ===================================================================

class TestCollectForgottenIds:

    def test_no_condensation_actions(self):
        evts = [_event(1), _event(2)]
        assert View._collect_forgotten_event_ids(evts) == set()

    def test_with_condensation_action(self):
        ca = CondensationAction(
            forgotten_events_start_id=2,
            forgotten_events_end_id=5,
        )
        ca._id = 10
        evts = [_event(1), ca, _event(6)]
        forgotten = View._collect_forgotten_event_ids(evts)
        # Should include the condensation action itself and the range
        assert 10 in forgotten
        # The forgotten range from CondensationAction.forgotten property
        for eid in ca.forgotten:
            assert eid in forgotten

    def test_with_condensation_request_action(self):
        cra = CondensationRequestAction()
        cra._id = 50
        evts = [_event(1), cra]
        forgotten = View._collect_forgotten_event_ids(evts)
        assert 50 in forgotten


# ===================================================================
# _find_summary_info
# ===================================================================

class TestFindSummaryInfo:

    def test_no_summary_returns_none(self):
        evts = [_event(1)]
        summary, offset = View._find_summary_info(evts)
        assert summary is None
        assert offset is None

    def test_finds_summary_from_condensation(self):
        ca = CondensationAction(
            forgotten_events_start_id=1,
            forgotten_events_end_id=3,
            summary="Summary text",
            summary_offset=1,
        )
        evts = [_event(0), ca, _event(4)]
        summary, offset = View._find_summary_info(evts)
        assert summary == "Summary text"
        assert offset == 1

    def test_returns_last_condensation_summary(self):
        ca1 = CondensationAction(
            forgotten_events_start_id=1,
            forgotten_events_end_id=2,
            summary="Old",
            summary_offset=0,
        )
        ca2 = CondensationAction(
            forgotten_events_start_id=3,
            forgotten_events_end_id=4,
            summary="New",
            summary_offset=1,
        )
        evts = [ca1, ca2]
        summary, offset = View._find_summary_info(evts)
        assert summary == "New"


# ===================================================================
# _check_unhandled_condensation_request
# ===================================================================

class TestCheckUnhandledRequest:

    def test_no_requests_returns_false(self):
        evts = [_event(1), _event(2)]
        assert View._check_unhandled_condensation_request(evts) is False

    def test_handled_request_returns_false(self):
        cra = CondensationRequestAction()
        ca = CondensationAction(
            forgotten_events_start_id=1, forgotten_events_end_id=2
        )
        evts = [cra, ca]
        assert View._check_unhandled_condensation_request(evts) is False

    def test_unhandled_request_returns_true(self):
        cra = CondensationRequestAction()
        evts = [_event(1), cra]
        assert View._check_unhandled_condensation_request(evts) is True


# ===================================================================
# from_events
# ===================================================================

class TestFromEvents:

    def test_simple_passthrough(self):
        evts = [_event(1), _event(2)]
        view = View.from_events(evts)
        assert len(view) == 2
        assert view.unhandled_condensation_request is False

    def test_filters_forgotten_events(self):
        e1 = _event(1)
        e2 = _event(2)
        e3 = _event(3)
        ca = CondensationAction(
            forgotten_events_start_id=2,
            forgotten_events_end_id=2,
        )
        ca._id = 10
        evts = [e1, e2, e3, ca]
        view = View.from_events(evts)
        # e2 is forgotten, ca itself should be forgotten too
        ids = [e.id for e in view.events]
        assert 2 not in ids
        assert 10 not in ids
