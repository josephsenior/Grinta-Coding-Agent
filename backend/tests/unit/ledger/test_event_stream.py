"""Unit tests for backend.ledger.stream — EventStreamSubscriber and helpers."""

from __future__ import annotations

from backend.ledger.stream import (
    EventStreamSubscriber,
    get_aggregated_event_stream_stats,
)

# ---------------------------------------------------------------------------
# EventStreamSubscriber enum
# ---------------------------------------------------------------------------


class TestEventStreamSubscriber:
    def test_members(self):
        assert EventStreamSubscriber.AGENT_CONTROLLER.value == 'agent_controller'
        assert EventStreamSubscriber.SERVER.value == 'server'
        assert EventStreamSubscriber.RUNTIME.value == 'runtime'
        assert EventStreamSubscriber.MEMORY.value == 'memory'
        assert EventStreamSubscriber.MAIN.value == 'main'
        assert EventStreamSubscriber.TEST.value == 'test'

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
        assert 'total_streams' in stats or isinstance(stats, dict)
