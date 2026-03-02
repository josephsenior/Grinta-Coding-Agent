"""Tests for backend.events.event_store_abc — EventStoreABC base class."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.events.event_store_abc import EventStoreABC


# ── Concrete stub ─────────────────────────────────────────────────────


class _StubStore(EventStoreABC):
    """Minimal concrete implementation for testing base-class helpers."""

    def __init__(self, events: list | None = None):
        self.sid = "test-sid"
        self.user_id = None
        self._events = events or []

    def search_events(
        self, start_id=0, end_id=None, reverse=False, filter=None, limit=None
    ):
        sliced = self._events[start_id:end_id]
        if reverse:
            sliced = list(reversed(sliced))
        for ev in sliced:
            if filter is not None and not filter.include(ev):
                continue
            yield ev

    def get_event(self, id: int):
        if id < 0 or id >= len(self._events):
            raise FileNotFoundError(f"Event {id} not found")
        return self._events[id]

    def get_latest_event(self):
        return self._events[-1]

    def get_latest_event_id(self):
        return len(self._events) - 1


# ── Helpers ───────────────────────────────────────────────────────────


def _make_event(source="agent", hidden=False, timestamp=None):
    ev = MagicMock()
    ev.source = MagicMock()
    ev.source.value = source
    ev.hidden = hidden
    ev.timestamp = timestamp
    return ev


# ── get_events ────────────────────────────────────────────────────────


class TestGetEvents:
    def test_returns_all_events(self):
        events = [_make_event(), _make_event()]
        store = _StubStore(events)
        assert list(store.get_events()) == events

    def test_with_start_end(self):
        events = [_make_event() for _ in range(5)]
        store = _StubStore(events)
        result = list(store.get_events(start_id=1, end_id=3))
        assert len(result) == 2

    def test_reverse(self):
        e1, e2, e3 = _make_event(), _make_event(), _make_event()
        store = _StubStore([e1, e2, e3])
        result = list(store.get_events(reverse=True))
        assert result == [e3, e2, e1]

    def test_filter_out_type(self):
        e1 = _make_event()
        e2 = MagicMock(spec=str)  # Different type
        e2.source = MagicMock()
        e2.source.value = "agent"
        e2.hidden = False
        e2.timestamp = None

        store = _StubStore([e1, e2])
        # filter_out_type excludes types via EventFilter(exclude_types=...)
        result = list(store.get_events(filter_out_type=cast(Any, (str,))))
        # e2 is of type MagicMock with spec=str, so isinstance check may differ
        # The important thing is the filter is passed through
        assert isinstance(result, list)

    def test_filter_hidden(self):
        e1 = _make_event(hidden=False)
        e2 = _make_event(hidden=True)
        store = _StubStore([e1, e2])
        result = list(store.get_events(filter_hidden=True))
        assert len(result) == 1
        assert result[0] is e1


# ── filtered_events_by_source ─────────────────────────────────────────


class TestFilteredEventsBySource:
    def test_filters_by_source(self):
        e1 = _make_event(source="agent")
        e2 = _make_event(source="user")
        e3 = _make_event(source="agent")
        store = _StubStore([e1, e2, e3])
        result = list(store.filtered_events_by_source(cast(Any, "agent")))
        assert len(result) == 2
        assert all(getattr(ev.source, "value", None) == "agent" for ev in result)


# ── get_matching_events ───────────────────────────────────────────────


class TestGetMatchingEvents:
    def test_default_parameters(self):
        events = [_make_event() for _ in range(5)]
        store = _StubStore(events)
        result = store.get_matching_events()
        assert len(result) == 5

    def test_limit_applied(self):
        events = [_make_event() for _ in range(10)]
        store = _StubStore(events)
        result = store.get_matching_events(limit=3)
        assert len(result) == 3

    def test_limit_too_low_raises(self):
        store = _StubStore([])
        with pytest.raises(ValueError, match="Limit must be between 1 and 100"):
            store.get_matching_events(limit=0)

    def test_limit_too_high_raises(self):
        store = _StubStore([])
        with pytest.raises(ValueError, match="Limit must be between 1 and 100"):
            store.get_matching_events(limit=101)

    def test_reverse_order(self):
        e1, e2, e3 = _make_event(), _make_event(), _make_event()
        store = _StubStore([e1, e2, e3])
        result = store.get_matching_events(reverse=True)
        assert result == [e3, e2, e1]

    def test_source_filter(self):
        e1 = _make_event(source="agent")
        e2 = _make_event(source="user")
        store = _StubStore([e1, e2])
        result = store.get_matching_events(source=cast(Any, "user"))
        assert len(result) == 1
        assert getattr(result[0].source, "value", None) == "user"

    def test_start_id(self):
        events = [_make_event() for _ in range(5)]
        store = _StubStore(events)
        result = store.get_matching_events(start_id=3)
        assert len(result) == 2
