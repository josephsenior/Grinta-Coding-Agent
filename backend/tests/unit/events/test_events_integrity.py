"""Tests for backend.events.integrity — iter_events_until_corrupt."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from backend.events.integrity import iter_events_until_corrupt


def _make_store(events: list, cur_id: int | None = None):
    """Build a mock EventStore with the given events list."""
    store = MagicMock()
    store.cur_id = cur_id if cur_id is not None else len(events)

    def _get_event(idx):
        if idx < 0 or idx >= len(events):
            raise FileNotFoundError(f"Event {idx} not found")
        ev = events[idx]
        if isinstance(ev, Exception):
            raise ev
        return ev

    store.get_event.side_effect = _get_event
    return store


def _make_event(id: int):
    ev = MagicMock()
    ev.id = id
    return ev


# ── Happy path ────────────────────────────────────────────────────────


class TestIterEventsHappyPath:
    def test_yields_all_events(self):
        events = [_make_event(i) for i in range(5)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store))
        assert len(result) == 5

    def test_empty_store(self):
        store = _make_store([], cur_id=0)
        result = list(iter_events_until_corrupt(store))
        assert result == []

    def test_start_id(self):
        events = [_make_event(i) for i in range(5)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store, start_id=3))
        assert len(result) == 2
        assert result[0].id == 3
        assert result[1].id == 4

    def test_limit(self):
        events = [_make_event(i) for i in range(10)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store, limit=3))
        assert len(result) == 3

    def test_negative_start_id_clamps_to_zero(self):
        events = [_make_event(i) for i in range(3)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store, start_id=-5))
        assert len(result) == 3


# ── Stops at corruption ───────────────────────────────────────────────


class TestIterEventsStopsAtCorruption:
    def test_stops_at_file_not_found(self):
        event0 = _make_event(0)
        events = [event0, FileNotFoundError("missing"), _make_event(2)]
        store = _make_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert len(result) == 1
        assert result[0].id == 0

    def test_stops_at_json_decode_error(self):
        event0 = _make_event(0)
        events = [event0, json.JSONDecodeError("bad", "", 0), _make_event(2)]
        store = _make_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert len(result) == 1

    def test_stops_at_value_error(self):
        event0 = _make_event(0)
        events = [event0, ValueError("corrupt"), _make_event(2)]
        store = _make_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert len(result) == 1


# ── Filter integration ────────────────────────────────────────────────


class TestIterEventsWithFilter:
    def test_filter_excludes_events(self):
        events = [_make_event(i) for i in range(5)]
        store = _make_store(events)
        filt = MagicMock()
        filt.include.side_effect = lambda ev: ev.id % 2 == 0
        result = list(iter_events_until_corrupt(store, event_filter=filt))
        assert len(result) == 3  # ids 0, 2, 4
        assert all(ev.id % 2 == 0 for ev in result)

    def test_filter_skips_without_counting_toward_limit(self):
        events = [_make_event(i) for i in range(10)]
        store = _make_store(events)
        filt = MagicMock()
        filt.include.side_effect = lambda ev: ev.id % 2 == 0
        result = list(iter_events_until_corrupt(store, event_filter=filt, limit=2))
        assert len(result) == 2
        assert result[0].id == 0
        assert result[1].id == 2

    def test_none_filter_includes_all(self):
        events = [_make_event(i) for i in range(3)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store, event_filter=None))
        assert len(result) == 3


# ── Edge cases ────────────────────────────────────────────────────────


class TestIterEventsEdgeCases:
    def test_corruption_at_first_event(self):
        events = [FileNotFoundError("gone")]
        store = _make_store(events, cur_id=1)
        result = list(iter_events_until_corrupt(store))
        assert result == []

    def test_limit_zero(self):
        events = [_make_event(0)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store, limit=0))
        assert result == []

    def test_limit_larger_than_events(self):
        events = [_make_event(i) for i in range(3)]
        store = _make_store(events)
        result = list(iter_events_until_corrupt(store, limit=100))
        assert len(result) == 3
