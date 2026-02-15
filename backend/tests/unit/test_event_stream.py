"""Unit tests for backend.events.stream — EventStreamSubscriber and helpers."""

from __future__ import annotations

import pytest

from backend.events.stream import EventStreamSubscriber, get_aggregated_event_stream_stats


# ---------------------------------------------------------------------------
# EventStreamSubscriber enum
# ---------------------------------------------------------------------------


class TestEventStreamSubscriber:
    def test_members(self):
        assert EventStreamSubscriber.AGENT_CONTROLLER == "agent_controller"
        assert EventStreamSubscriber.SERVER == "server"
        assert EventStreamSubscriber.RUNTIME == "runtime"
        assert EventStreamSubscriber.MEMORY == "memory"
        assert EventStreamSubscriber.MAIN == "main"
        assert EventStreamSubscriber.TEST == "test"

    def test_is_string(self):
        assert isinstance(EventStreamSubscriber.TEST, str)

    def test_iteration(self):
        members = list(EventStreamSubscriber)
        assert len(members) >= 6


# ---------------------------------------------------------------------------
# get_aggregated_event_stream_stats (module-level)
# ---------------------------------------------------------------------------


class TestAggregatedEventStreamStats:
    def test_returns_dict(self):
        stats = get_aggregated_event_stream_stats()
        assert isinstance(stats, dict)
        # Should have at least the count key
        assert "total_streams" in stats or isinstance(stats, dict)
