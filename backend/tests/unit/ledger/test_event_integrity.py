"""Unit tests for backend.ledger.integrity — corrupt event recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from unittest.mock import MagicMock, PropertyMock


from backend.ledger.integrity import iter_events_until_corrupt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_store(events: Mapping[int, object], cur_id: int):
    """Build a mock EventStore.

    events: mapping from id → event object (or exception to raise).
    cur_id: the store's cur_id property (exclusive upper bound).
    """
    store = MagicMock()
    type(store).cur_id = PropertyMock(return_value=cur_id)

    def get_event(idx):
        val = events.get(idx)
        if val is None:
            raise FileNotFoundError(f"No event at {idx}")
        if isinstance(val, Exception):
            raise val
        return val

    store.get_event = MagicMock(side_effect=get_event)
    return store


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_all_valid(self):
        events = {0: "ev0", 1: "ev1", 2: "ev2"}
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert result == ["ev0", "ev1", "ev2"]

    def test_empty_store(self):
        store = _make_event_store({}, cur_id=0)
        assert list(iter_events_until_corrupt(store)) == []

    def test_start_id(self):
        events = {0: "ev0", 1: "ev1", 2: "ev2"}
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store, start_id=1))
        assert result == ["ev1", "ev2"]

    def test_limit(self):
        events = {0: "ev0", 1: "ev1", 2: "ev2"}
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store, limit=2))
        assert result == ["ev0", "ev1"]


# ---------------------------------------------------------------------------
# Corrupt events stop iteration
# ---------------------------------------------------------------------------


class TestCorruptEvents:
    def test_missing_file_stops(self):
        events = {0: "ev0"}  # id 1 is missing → FileNotFoundError
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert result == ["ev0"]

    def test_json_decode_error_stops(self):
        events = {0: "ev0", 1: json.JSONDecodeError("bad", "", 0)}
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert result == ["ev0"]

    def test_value_error_stops(self):
        events = {0: "ev0", 1: ValueError("corrupt")}
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert result == ["ev0"]

    def test_first_event_corrupt(self):
        events = {0: json.JSONDecodeError("bad", "", 0)}
        store = _make_event_store(events, cur_id=3)
        result = list(iter_events_until_corrupt(store))
        assert result == []


# ---------------------------------------------------------------------------
# EventFilter integration
# ---------------------------------------------------------------------------


class TestEventFilter:
    def test_filter_skips_events(self):
        events = {0: "ev0", 1: "ev1", 2: "ev2"}
        store = _make_event_store(events, cur_id=3)

        filt = MagicMock()
        # Only include even-indexed events
        filt.include = MagicMock(side_effect=lambda ev: ev in ("ev0", "ev2"))

        result = list(iter_events_until_corrupt(store, event_filter=filt))
        assert result == ["ev0", "ev2"]

    def test_filter_with_limit(self):
        events = {0: "ev0", 1: "ev1", 2: "ev2", 3: "ev3"}
        store = _make_event_store(events, cur_id=4)

        filt = MagicMock()
        filt.include = MagicMock(return_value=True)

        result = list(iter_events_until_corrupt(store, event_filter=filt, limit=2))
        assert len(result) == 2

    def test_filter_all_excluded_returns_empty(self):
        events = {0: "ev0", 1: "ev1"}
        store = _make_event_store(events, cur_id=2)

        filt = MagicMock()
        filt.include = MagicMock(return_value=False)

        result = list(iter_events_until_corrupt(store, event_filter=filt))
        assert result == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_negative_start_id_clamped(self):
        events = {0: "ev0"}
        store = _make_event_store(events, cur_id=1)
        result = list(iter_events_until_corrupt(store, start_id=-5))
        assert result == ["ev0"]

    def test_start_id_beyond_cur_id(self):
        events = {0: "ev0"}
        store = _make_event_store(events, cur_id=1)
        result = list(iter_events_until_corrupt(store, start_id=10))
        assert result == []

    def test_limit_zero(self):
        events = {0: "ev0"}
        store = _make_event_store(events, cur_id=1)
        result = list(iter_events_until_corrupt(store, limit=0))
        assert result == []
