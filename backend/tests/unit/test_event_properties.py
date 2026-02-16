"""Tests for backend.events.event — Event dataclass property logic."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.core.schemas import EventSource
from backend.events.event import Event


class TestEventDefaults:
    def test_id_default(self):
        e = Event()
        assert e.id == Event.INVALID_ID

    def test_sequence_default(self):
        e = Event()
        assert e.sequence == Event.INVALID_ID

    def test_timestamp_default(self):
        e = Event()
        assert e.timestamp is None

    def test_source_default(self):
        e = Event()
        assert e.source is None

    def test_cause_default(self):
        e = Event()
        assert e.cause is None

    def test_hidden_default(self):
        e = Event()
        assert e.hidden is False

    def test_timeout_default(self):
        e = Event()
        assert e.timeout is None

    def test_message_default(self):
        e = Event()
        assert e.message == ""

    def test_tool_call_metadata_default(self):
        e = Event()
        assert e.tool_call_metadata is None

    def test_response_id_default(self):
        e = Event()
        assert e.response_id is None


class TestEventId:
    def test_set_and_get(self):
        e = Event()
        e.id = 42
        assert e.id == 42

    def test_set_none(self):
        e = Event()
        e.id = None
        assert e.id == Event.INVALID_ID


class TestEventSequence:
    def test_set_and_get(self):
        e = Event()
        e.sequence = 10
        assert e.sequence == 10

    def test_set_none(self):
        e = Event()
        e.sequence = None
        assert e.sequence == Event.INVALID_ID


class TestEventTimestamp:
    def test_set_datetime(self):
        e = Event()
        dt = datetime(2025, 6, 15, 12, 0, 0)
        e.timestamp = dt
        assert e.timestamp == "2025-06-15T12:00:00"

    def test_set_non_datetime_ignored(self):
        e = Event()
        e.timestamp = "not-a-datetime"  # type: ignore
        # timestamp setter checks isinstance(value, datetime)
        assert e.timestamp is None


class TestEventSource:
    def test_set_enum(self):
        e = Event()
        e.source = EventSource.USER
        assert e.source == EventSource.USER

    def test_set_valid_string(self):
        e = Event()
        e.source = EventSource.USER.value
        assert e.source == EventSource.USER

    def test_set_none(self):
        e = Event()
        e.source = EventSource.USER
        e.source = None
        assert e.source is None

    def test_set_invalid_type(self):
        e = Event()
        with pytest.raises(TypeError, match="source must be"):
            e.source = 123  # type: ignore


class TestEventCause:
    def test_set_and_get(self):
        e = Event()
        e.cause = 5
        assert e.cause == 5

    def test_set_none(self):
        e = Event()
        e.cause = None
        assert e.cause is None


class TestEventHidden:
    def test_set_true(self):
        e = Event()
        e.hidden = True
        assert e.hidden is True

    def test_set_false(self):
        e = Event()
        e.hidden = True
        e.hidden = False
        assert e.hidden is False


class TestEventTimeout:
    def test_set_hard_timeout(self):
        e = Event()
        e.set_hard_timeout(30.0)
        assert e.timeout == 30.0

    def test_set_hard_timeout_none(self):
        e = Event()
        e.set_hard_timeout(10.0)
        e.set_hard_timeout(None)
        assert e.timeout is None


class TestEventMessage:
    def test_with_message(self):
        e = Event()
        e._message = "Hello"
        assert e.message == "Hello"

    def test_with_none_message(self):
        e = Event()
        e._message = None
        assert e.message is None


class TestEventToolCallMetadata:
    def test_set_and_get_duck_typed(self):
        e = Event()
        meta = SimpleNamespace(
            function_name="test", tool_call_id="tc1", total_calls_in_response=1
        )
        e.tool_call_metadata = meta
        assert e.tool_call_metadata is not None
        assert e.tool_call_metadata.function_name == "test"

    def test_rejects_incomplete_duck_type(self):
        e = Event()
        bad = SimpleNamespace(function_name="test")  # missing required attrs
        e._tool_call_metadata = bad
        assert e.tool_call_metadata is None


class TestEventResponseId:
    def test_set_and_get(self):
        e = Event()
        e.response_id = "resp-123"
        assert e.response_id == "resp-123"
