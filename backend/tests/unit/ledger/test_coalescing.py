"""Unit tests for backend.ledger.coalescing — event batching & flush."""

from __future__ import annotations

import time
from unittest.mock import MagicMock


from backend.ledger.coalescing import CoalescedBatch, EventCoalescer, _COALESCE_TYPES
from backend.ledger.event import Event, EventSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(type_name: str = "StreamingChunkAction") -> Event:
    """Create a mock event whose class name is *type_name*."""
    ev = MagicMock(spec=Event)
    ev.source = EventSource.AGENT
    type(ev).__name__ = type_name
    return ev


# ---------------------------------------------------------------------------
# CoalescedBatch
# ---------------------------------------------------------------------------


class TestCoalescedBatch:
    def test_init(self):
        ev = _event()
        batch = CoalescedBatch(ev)
        assert batch.size == 1
        assert batch.event_type == "StreamingChunkAction"
        assert batch.age_ms >= 0

    def test_add(self):
        batch = CoalescedBatch(_event())
        batch.add(_event())
        assert batch.size == 2

    def test_age_increases(self):
        batch = CoalescedBatch(_event())
        # Force age by setting first_ts in the past
        batch.first_ts = time.monotonic() - 0.5
        assert batch.age_ms >= 400  # at least 400 ms


# ---------------------------------------------------------------------------
# should_coalesce
# ---------------------------------------------------------------------------


class TestShouldCoalesce:
    def test_eligible_types(self):
        c = EventCoalescer()
        for t in _COALESCE_TYPES:
            assert c.should_coalesce(_event(t)) is True

    def test_ineligible_type(self):
        c = EventCoalescer()
        assert c.should_coalesce(_event("CmdRunAction")) is False

    def test_custom_types(self):
        c = EventCoalescer(coalesce_types={"MyCustomEvent"})
        assert c.should_coalesce(_event("MyCustomEvent")) is True
        assert c.should_coalesce(_event("StreamingChunkAction")) is False


# ---------------------------------------------------------------------------
# absorb
# ---------------------------------------------------------------------------


class TestAbsorb:
    def test_first_absorb_returns_none(self):
        c = EventCoalescer(window_ms=500, max_batch=10)
        result = c.absorb(_event())
        assert result is None

    def test_auto_flush_on_max_batch(self):
        c = EventCoalescer(window_ms=10_000, max_batch=3)
        c.absorb(_event())  # 1
        c.absorb(_event())  # 2
        result = c.absorb(_event())  # 3 → auto-flush
        assert result is not None

    def test_auto_flush_on_window_expiry(self):
        c = EventCoalescer(window_ms=0, max_batch=100)  # 0ms → immediate
        c.absorb(_event())
        # The batch was created; next absorb should see it expired
        result = c.absorb(_event())
        # Depending on timing, may or may not flush; at least no error
        # With window_ms=0, age_ms > 0 is always true so auto-flush fires
        assert result is not None

    def test_coalesced_count_incremented(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        c.absorb(_event())
        c.absorb(_event())
        assert c._coalesced_count == 1  # second absorb increments

    def test_different_types_separate_batches(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        c.absorb(_event("StreamingChunkAction"))
        c.absorb(_event("NullObservation"))
        assert len(c._pending) == 2


# ---------------------------------------------------------------------------
# flush_all / flush_expired
# ---------------------------------------------------------------------------


class TestFlush:
    def test_flush_all_empties_pending(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        c.absorb(_event("StreamingChunkAction"))
        c.absorb(_event("NullObservation"))
        results = c.flush_all()
        assert len(results) == 2
        assert not c._pending

    def test_flush_all_empty(self):
        c = EventCoalescer()
        results = c.flush_all()
        assert results == []

    def test_flush_expired_only(self):
        c = EventCoalescer(window_ms=0, max_batch=100)
        c.absorb(_event("StreamingChunkAction"))
        # With window_ms=0, everything is expired immediately
        results = c.flush_expired()
        assert len(results) == 1

    def test_flush_expired_nothing_expired(self):
        c = EventCoalescer(window_ms=999_999, max_batch=100)
        c.absorb(_event())
        results = c.flush_expired()
        assert results == []

    def test_flushed_count_incremented(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        c.absorb(_event())
        c.flush_all()
        assert c._flushed_count == 1


# ---------------------------------------------------------------------------
# _flush_batch edge cases
# ---------------------------------------------------------------------------


class TestFlushBatch:
    def test_nonexistent_type(self):
        c = EventCoalescer()
        result = c._flush_batch("NoSuchType")
        assert result is None

    def test_streaming_merge_returns_last(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        ev1 = _event("StreamingChunkAction")
        ev2 = _event("StreamingChunkAction")
        c.absorb(ev1)
        c.absorb(ev2)
        results = c.flush_all()
        assert len(results) == 1
        assert results[0] is ev2  # last event

    def test_non_streaming_returns_last(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        ev1 = _event("NullObservation")
        ev2 = _event("NullObservation")
        c.absorb(ev1)
        c.absorb(ev2)
        results = c.flush_all()
        assert results[0] is ev2


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_keys(self):
        c = EventCoalescer(window_ms=100, max_batch=20)
        snap = c.snapshot()
        assert snap["pending_batches"] == 0
        assert snap["pending_events"] == 0
        assert snap["coalesced_total"] == 0
        assert snap["flushed_total"] == 0
        assert snap["window_ms"] == 100
        assert snap["max_batch"] == 20

    def test_snapshot_after_absorb(self):
        c = EventCoalescer(window_ms=5000, max_batch=100)
        c.absorb(_event())
        c.absorb(_event())
        snap = c.snapshot()
        assert snap["pending_batches"] == 1
        assert snap["pending_events"] == 2
        assert snap["coalesced_total"] == 1
