"""Unit tests for backend.events.event_filter — event stream filtering."""

from __future__ import annotations

import pytest

from backend.events.event import Event, EventSource
from backend.events.event_filter import EventFilter
from backend.events.action.message import MessageAction
from backend.events.observation.empty import NullObservation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg_event(content="hello", source=EventSource.USER, hidden=False, ts=None):
    ev = MessageAction(content=content)
    ev.source = source
    ev.hidden = hidden
    if ts is not None:
        ev._timestamp = ts  # bypass datetime-only setter
    return ev


def _null_obs(source=EventSource.ENVIRONMENT, hidden=False, ts=None):
    ev = NullObservation(content="")
    ev.source = source
    ev.hidden = hidden
    if ts is not None:
        ev._timestamp = ts  # bypass datetime-only setter
    return ev


# ---------------------------------------------------------------------------
# Default filter (all events pass)
# ---------------------------------------------------------------------------


class TestDefaultFilter:
    def test_include_all(self):
        f = EventFilter()
        assert f.include(_msg_event()) is True
        assert f.include(_null_obs()) is True

    def test_exclude_is_inverse(self):
        f = EventFilter()
        ev = _msg_event()
        assert f.exclude(ev) is not f.include(ev)


# ---------------------------------------------------------------------------
# Type filtering
# ---------------------------------------------------------------------------


class TestTypeFilters:
    def test_include_types(self):
        f = EventFilter(include_types=(MessageAction,))
        assert f.include(_msg_event()) is True
        assert f.include(_null_obs()) is False

    def test_exclude_types(self):
        f = EventFilter(exclude_types=(NullObservation,))
        assert f.include(_msg_event()) is True
        assert f.include(_null_obs()) is False

    def test_include_and_exclude_combined(self):
        # include_types takes precedence — must be one of the types
        f = EventFilter(
            include_types=(MessageAction, NullObservation),
            exclude_types=(NullObservation,),
        )
        assert f.include(_msg_event()) is True
        assert f.include(_null_obs()) is False


# ---------------------------------------------------------------------------
# Source filtering
# ---------------------------------------------------------------------------


class TestSourceFilter:
    def test_filter_by_user(self):
        f = EventFilter(source="user")
        assert f.include(_msg_event(source=EventSource.USER)) is True
        assert f.include(_msg_event(source=EventSource.AGENT)) is False

    def test_filter_by_agent(self):
        f = EventFilter(source="agent")
        assert f.include(_msg_event(source=EventSource.AGENT)) is True
        assert f.include(_msg_event(source=EventSource.USER)) is False

    def test_no_source_passes_all(self):
        f = EventFilter(source=None)
        assert f.include(_msg_event(source=EventSource.USER)) is True
        assert f.include(_msg_event(source=EventSource.AGENT)) is True


# ---------------------------------------------------------------------------
# Date filtering
# ---------------------------------------------------------------------------


class TestDateFilters:
    def test_start_date_filter(self):
        f = EventFilter(start_date="2024-06-01T00:00:00")
        assert f.include(_msg_event(ts="2024-07-01T00:00:00")) is True
        assert f.include(_msg_event(ts="2024-05-01T00:00:00")) is False

    def test_end_date_filter(self):
        f = EventFilter(end_date="2024-06-01T00:00:00")
        assert f.include(_msg_event(ts="2024-05-01T00:00:00")) is True
        assert f.include(_msg_event(ts="2024-07-01T00:00:00")) is False

    def test_date_range(self):
        f = EventFilter(
            start_date="2024-01-01T00:00:00",
            end_date="2024-12-31T23:59:59",
        )
        assert f.include(_msg_event(ts="2024-06-15T12:00:00")) is True
        assert f.include(_msg_event(ts="2023-06-15T12:00:00")) is False
        assert f.include(_msg_event(ts="2025-01-01T00:00:00")) is False

    def test_no_timestamp_passes(self):
        f = EventFilter(start_date="2024-01-01T00:00:00")
        ev = _msg_event()
        ev.timestamp = None
        assert f.include(ev) is True


# ---------------------------------------------------------------------------
# Hidden filtering
# ---------------------------------------------------------------------------


class TestHiddenFilter:
    def test_exclude_hidden(self):
        f = EventFilter(exclude_hidden=True)
        assert f.include(_msg_event(hidden=False)) is True
        assert f.include(_msg_event(hidden=True)) is False

    def test_include_hidden_by_default(self):
        f = EventFilter(exclude_hidden=False)
        assert f.include(_msg_event(hidden=True)) is True


# ---------------------------------------------------------------------------
# Query (text search) filtering
# ---------------------------------------------------------------------------


class TestQueryFilter:
    def test_query_match(self):
        f = EventFilter(query="hello")
        assert f.include(_msg_event(content="hello world")) is True

    def test_query_no_match(self):
        f = EventFilter(query="foobar")
        assert f.include(_msg_event(content="hello world")) is False

    def test_case_insensitive(self):
        f = EventFilter(query="HELLO")
        assert f.include(_msg_event(content="hello world")) is True

    def test_no_query_passes(self):
        f = EventFilter(query=None)
        assert f.include(_msg_event()) is True


# ---------------------------------------------------------------------------
# Composite filtering
# ---------------------------------------------------------------------------


class TestCompositeFilter:
    def test_all_criteria(self):
        f = EventFilter(
            include_types=(MessageAction,),
            source="user",
            query="hello",
            exclude_hidden=True,
        )
        good = _msg_event(content="hello", source=EventSource.USER, hidden=False)
        assert f.include(good) is True

        bad_type = _null_obs()
        bad_type.source = EventSource.USER
        assert f.include(bad_type) is False

        bad_source = _msg_event(content="hello", source=EventSource.AGENT)
        assert f.include(bad_source) is False

        bad_query = _msg_event(content="goodbye", source=EventSource.USER)
        assert f.include(bad_query) is False

        bad_hidden = _msg_event(
            content="hello", source=EventSource.USER, hidden=True
        )
        assert f.include(bad_hidden) is False
