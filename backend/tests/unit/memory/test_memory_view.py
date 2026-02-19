"""Tests for backend.memory.view module — View class and from_events factory."""

import pytest

from backend.events.action.message import MessageAction
from backend.events.event import EventSource
from backend.memory.view import View


def _make_event(event_id=1, content="test"):
    """Create a real MessageAction event."""
    e = MessageAction(content=content)
    e._id = event_id
    e.source = EventSource.USER
    return e


class TestViewBasics:
    def test_len(self):
        events = [_make_event(i) for i in range(5)]
        v = View(events=events)
        assert len(v) == 5

    def test_len_empty(self):
        v = View(events=[])
        assert not v

    def test_iter(self):
        events = [_make_event(i) for i in range(3)]
        v = View(events=events)
        result = list(v)
        assert len(result) == 3

    def test_getitem_int(self):
        events = [_make_event(i, content=f"msg-{i}") for i in range(3)]
        v = View(events=events)
        assert v[0].content == "msg-0"
        assert v[2].content == "msg-2"

    def test_getitem_negative(self):
        events = [_make_event(i, content=f"msg-{i}") for i in range(3)]
        v = View(events=events)
        assert v[-1].content == "msg-2"

    def test_getitem_slice(self):
        events = [_make_event(i) for i in range(5)]
        v = View(events=events)
        sliced = v[1:3]
        assert len(sliced) == 2

    def test_getitem_invalid_type_raises(self):
        v = View(events=[])
        with pytest.raises(TypeError, match="Invalid key type"):
            v["bad"]

    def test_getitem_index_error(self):
        v = View(events=[_make_event(0)])
        with pytest.raises(IndexError):
            v[5]

    def test_default_unhandled_condensation(self):
        v = View(events=[])
        assert v.unhandled_condensation_request is False


class TestCollectForgottenEventIds:
    def test_no_condensation_actions(self):
        events = [_make_event(1), _make_event(2)]
        result = View._collect_forgotten_event_ids(events)
        assert result == set()

    def test_with_condensation_action(self):
        from backend.events.action.agent import CondensationAction

        ca = CondensationAction(forgotten_event_ids=[10, 20, 30])
        ca._id = 99
        events = [_make_event(1), ca]
        result = View._collect_forgotten_event_ids(events)
        assert 10 in result
        assert 20 in result
        assert 30 in result
        assert 99 in result

    def test_with_condensation_request_action(self):
        from backend.events.action.agent import CondensationRequestAction

        cra = CondensationRequestAction()
        cra._id = 50
        result = View._collect_forgotten_event_ids([_make_event(1), cra])
        assert 50 in result


class TestFindSummaryInfo:
    def test_no_summary(self):
        events = [_make_event(1)]
        summary, offset = View._find_summary_info(events)
        assert summary is None
        assert offset is None

    def test_with_summary(self):
        from backend.events.action.agent import CondensationAction

        ca = CondensationAction(
            forgotten_event_ids=[1],
            summary="AI decided to use X",
            summary_offset=0,
        )
        events = [_make_event(1), ca]
        summary, offset = View._find_summary_info(events)
        assert summary == "AI decided to use X"
        assert offset == 0


class TestCheckUnhandledCondensationRequest:
    def test_no_events(self):
        assert View._check_unhandled_condensation_request([]) is False

    def test_only_normal_events(self):
        events = [_make_event(1), _make_event(2)]
        assert View._check_unhandled_condensation_request(events) is False

    def test_handled_request(self):
        from backend.events.action.agent import (
            CondensationAction,
            CondensationRequestAction,
        )

        cra = CondensationRequestAction()
        ca = CondensationAction(forgotten_event_ids=[1])
        events = [cra, ca]
        assert View._check_unhandled_condensation_request(events) is False

    def test_unhandled_request(self):
        from backend.events.action.agent import CondensationRequestAction

        cra = CondensationRequestAction()
        events = [_make_event(1), cra]
        assert View._check_unhandled_condensation_request(events) is True


class TestFromEvents:
    def test_empty_events(self):
        v = View.from_events([])
        assert not v
        assert v.unhandled_condensation_request is False

    def test_filters_forgotten(self):
        from backend.events.action.agent import CondensationAction

        e1 = _make_event(1)
        e2 = _make_event(2)
        ca = CondensationAction(forgotten_event_ids=[1])
        ca._id = 99  # The action itself should also be removed
        events = [e1, e2, ca]
        v = View.from_events(events)
        # e1 (id=1) is forgotten, ca (id=99) is forgotten
        event_ids = [e.id for e in v.events]
        assert 1 not in event_ids
        assert 99 not in event_ids
        assert 2 in event_ids
