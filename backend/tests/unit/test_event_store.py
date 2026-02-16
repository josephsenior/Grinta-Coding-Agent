"""Tests for backend.events.event_store — _CachePage and EventStore helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.events.event_store import EventStore, _CachePage, _DUMMY_PAGE


# ===================================================================
# _CachePage
# ===================================================================

class TestCachePage:

    def test_covers_inside_range(self):
        page = _CachePage(events=[{}, {}, {}], start=10, end=13)
        assert page.covers(10) is True
        assert page.covers(12) is True

    def test_covers_below_range(self):
        page = _CachePage(events=[], start=10, end=13)
        assert page.covers(9) is False

    def test_covers_at_end(self):
        page = _CachePage(events=[], start=10, end=13)
        assert page.covers(13) is False  # end is exclusive

    def test_get_event_from_page(self):
        """get_event returns deserialized event for valid index."""
        # We need a serializable dict that event_from_dict can parse.
        # Use a minimal MessageAction-like dict.
        action_dict = {
            "id": 10,
            "action": "message",
            "args": {"content": "hello", "image_urls": [], "wait_for_response": False},
            "message": "hello",
        }
        page = _CachePage(events=[action_dict], start=10, end=11)
        event = page.get_event(10)
        assert event is not None

    def test_get_event_none_events(self):
        page = _CachePage(events=None, start=0, end=5)
        assert page.get_event(2) is None


class TestDummyPage:

    def test_dummy_page_never_covers(self):
        assert _DUMMY_PAGE.covers(0) is False
        assert _DUMMY_PAGE.covers(100) is False
        assert _DUMMY_PAGE.covers(-1) is False

    def test_dummy_page_get_event_returns_none(self):
        assert _DUMMY_PAGE.get_event(0) is None


# ===================================================================
# EventStore — static / instance helpers
# ===================================================================

class TestEventStoreHelpers:

    def test_get_id_from_filename(self):
        assert EventStore._get_id_from_filename("events/42.json") == 42
        assert EventStore._get_id_from_filename("0.json") == 0

    def test_get_id_from_bad_filename(self):
        assert EventStore._get_id_from_filename("events/bad.json") == -1

    def test_normalize_search_range_defaults(self):
        """end_id=None falls back to cur_id."""
        fs = MagicMock()
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        store._cur_id = 5
        start, end = store._normalize_search_range(0, None)
        assert start == 0
        assert end == 5  # cur_id

    def test_normalize_search_range_explicit_end(self):
        fs = MagicMock()
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        store._cur_id = 100
        start, end = store._normalize_search_range(2, 7)
        assert start == 2
        assert end == 8  # end_id + 1

    def test_setup_reverse_search_forward(self):
        fs = MagicMock()
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        s, e, step = store._setup_reverse_search(0, 10, reverse=False)
        assert s == 0
        assert e == 10
        assert step == 1

    def test_setup_reverse_search_backward(self):
        fs = MagicMock()
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        s, e, step = store._setup_reverse_search(0, 10, reverse=True)
        assert step == -1
        # start and end get flipped
        assert s == 9  # end-1
        assert e == -1  # start-1


class TestEventStoreCurId:
    def test_cur_id_lazy_calc_empty(self):
        """cur_id returns 0 when no events on disk."""
        fs = MagicMock()
        fs.list.return_value = []
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        assert store.cur_id == 0

    def test_cur_id_lazy_calc_with_events(self):
        fs = MagicMock()
        fs.list.return_value = ["0.json", "1.json", "2.json"]
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        assert store.cur_id == 3  # max(0,1,2) + 1

    def test_cur_id_setter(self):
        fs = MagicMock()
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        store.cur_id = 42
        assert store.cur_id == 42

    def test_cur_id_file_not_found(self):
        fs = MagicMock()
        fs.list.side_effect = FileNotFoundError
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        assert store.cur_id == 0


class TestEventStoreGetLatest:
    def test_get_latest_event_id(self):
        fs = MagicMock()
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        store._cur_id = 10
        assert store.get_latest_event_id() == 9


class TestEventStoreCachePage:
    def test_load_cache_page_success(self):
        events_data = [{"id": 0, "action": "message", "args": {"content": "hi", "image_urls": [], "wait_for_response": False}, "message": "hi"}]
        fs = MagicMock()
        fs.read.return_value = json.dumps(events_data)
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        page = store._load_cache_page(0, 1)
        assert page.events is not None
        assert len(page.events) == 1
        assert page.start == 0
        assert page.end == 1

    def test_load_cache_page_file_not_found(self):
        fs = MagicMock()
        fs.read.side_effect = FileNotFoundError
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        page = store._load_cache_page(0, 25)
        assert page.events is None

    def test_load_cache_page_corrupt_json(self):
        fs = MagicMock()
        fs.read.return_value = "not json"
        store = EventStore(sid="s1", file_store=fs, user_id=None)
        page = store._load_cache_page(0, 25)
        assert page.events is None

    def test_load_cache_page_for_index(self):
        fs = MagicMock()
        fs.read.side_effect = FileNotFoundError
        store = EventStore(sid="s1", file_store=fs, user_id=None, cache_size=25)
        page = store._load_cache_page_for_index(30)
        # 30 % 25 = 5, so start = 25
        assert page.start == 25
        assert page.end == 50
