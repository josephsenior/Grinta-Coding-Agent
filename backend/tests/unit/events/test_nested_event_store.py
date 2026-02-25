"""Tests for backend.events.nested_event_store — HTTP-backed NestedEventStore."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.events.nested_event_store import NestedEventStore


# ── _build_search_params ─────────────────────────────────────────────


class TestBuildSearchParams:
    def setup_method(self):
        self.store = NestedEventStore(
            base_url="http://test:3000",
            sid="s1",
            user_id="u1",
        )

    def test_forward_default(self):
        params = self.store._build_search_params(
            start_cursor=0, end_cursor=None, reverse=False, limit=None
        )
        assert params == {"start_id": 0, "reverse": False}

    def test_forward_with_limit(self):
        params = self.store._build_search_params(
            start_cursor=5, end_cursor=None, reverse=False, limit=50
        )
        assert params["start_id"] == 5
        assert params["limit"] == 50

    def test_limit_capped_at_100(self):
        params = self.store._build_search_params(
            start_cursor=0, end_cursor=None, reverse=False, limit=999
        )
        assert params["limit"] == 100

    def test_reverse_with_end_cursor(self):
        params = self.store._build_search_params(
            start_cursor=0, end_cursor=50, reverse=True, limit=None
        )
        assert params["reverse"] is True
        assert params["end_id"] == 50

    def test_reverse_without_end_cursor(self):
        params = self.store._build_search_params(
            start_cursor=0, end_cursor=None, reverse=True, limit=None
        )
        assert "end_id" not in params


# ── _update_cursors ──────────────────────────────────────────────────


class TestUpdateCursors:
    def setup_method(self):
        self.store = NestedEventStore(
            base_url="http://test:3000",
            sid="s1",
            user_id="u1",
        )

    def test_reverse_with_page_min(self):
        start, end = self.store._update_cursors(
            reverse=True, page_min_id=10, forward_next_start=0, start_cursor=0
        )
        assert start == 0
        assert end == 9  # page_min_id - 1

    def test_forward(self):
        start, end = self.store._update_cursors(
            reverse=False, page_min_id=None, forward_next_start=25, start_cursor=0
        )
        assert start == 25
        assert end is None

    def test_reverse_no_page_min(self):
        start, end = self.store._update_cursors(
            reverse=True, page_min_id=None, forward_next_start=0, start_cursor=5
        )
        assert start == 5
        assert end is None


# ── _process_event ───────────────────────────────────────────────────


class TestProcessEvent:
    def setup_method(self):
        self.store = NestedEventStore(
            base_url="http://test:3000",
            sid="s1",
            user_id="u1",
        )

    def test_event_at_end_id_no_filter(self):
        ev = MagicMock(id=10)
        should_yield, should_stop = self.store._process_event(
            ev, end_id=10, filter=None, limit=None
        )
        assert should_yield is True
        assert should_stop is True

    def test_event_at_end_id_excluded_by_filter(self):
        ev = MagicMock(id=10)
        filt = MagicMock()
        filt.include.return_value = False
        should_yield, should_stop = self.store._process_event(
            ev, end_id=10, filter=filt, limit=None
        )
        assert should_yield is False
        assert should_stop is True

    def test_event_excluded_by_filter(self):
        ev = MagicMock(id=5)
        filt = MagicMock()
        filt.exclude.return_value = True
        should_yield, should_stop = self.store._process_event(
            ev, end_id=None, filter=filt, limit=None
        )
        assert should_yield is False
        assert should_stop is False

    def test_normal_event_no_filter(self):
        ev = MagicMock(id=5)
        should_yield, should_stop = self.store._process_event(
            ev, end_id=None, filter=None, limit=None
        )
        assert should_yield is True
        assert should_stop is False


# ── get_event / get_latest_event ─────────────────────────────────────


class TestGetEvent:
    def setup_method(self):
        self.store = NestedEventStore(
            base_url="http://test:3000",
            sid="s1",
            user_id="u1",
        )

    def test_get_event_not_found(self):
        with patch.object(self.store, "search_events", return_value=iter([])):
            with pytest.raises(FileNotFoundError, match="no_event"):
                self.store.get_event(99)

    def test_get_event_found(self):
        ev = MagicMock(id=99)
        with patch.object(self.store, "search_events", return_value=iter([ev])):
            result = self.store.get_event(99)
            assert result is ev

    def test_get_latest_event_not_found(self):
        with patch.object(self.store, "search_events", return_value=iter([])):
            with pytest.raises(FileNotFoundError, match="no_event"):
                self.store.get_latest_event()

    def test_get_latest_event_found(self):
        ev = MagicMock(id=100)
        with patch.object(self.store, "search_events", return_value=iter([ev])):
            result = self.store.get_latest_event()
            assert result is ev

    def test_get_latest_event_id(self):
        ev = MagicMock(id=42)
        with patch.object(self.store, "get_latest_event", return_value=ev):
            assert self.store.get_latest_event_id() == 42


# ── dataclass fields ─────────────────────────────────────────────────


class TestDataclass:
    def test_defaults(self):
        store = NestedEventStore(
            base_url="http://localhost:3000",
            sid="abc",
            user_id="user1",
        )
        assert store.user_id == "user1"
