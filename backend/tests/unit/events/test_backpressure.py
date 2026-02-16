"""Unit tests for backend.events.backpressure — queue policy & stats."""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.events.backpressure import BackpressureManager
from backend.events.event import Event, EventSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(eid: int = 1) -> Event:
    """Return a minimal Event for queue operations."""
    ev = Event()
    ev._id = eid
    ev.source = EventSource.AGENT
    return ev


def _make_queue(maxsize: int = 3) -> asyncio.Queue:
    return asyncio.Queue(maxsize=maxsize)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestBackpressureInit:
    def test_explicit_params(self):
        bp = BackpressureManager(
            max_queue_size=50,
            drop_policy="drop_newest",
            hwm_ratio=0.8,
            block_timeout=2.0,
            rate_window_seconds=120,
        )
        assert bp.max_queue_size == 50
        assert bp.drop_policy == "drop_newest"
        assert bp.hwm_ratio == 0.8
        assert bp.block_timeout == 2.0

    def test_unknown_policy_falls_back(self):
        bp = BackpressureManager(drop_policy="nonsense")
        assert bp.drop_policy == "drop_oldest"

    def test_hwm_ratio_clamped_low(self):
        bp = BackpressureManager(hwm_ratio=0.01)
        assert bp.hwm_ratio >= 0.1

    def test_hwm_ratio_clamped_high(self):
        bp = BackpressureManager(hwm_ratio=1.5)
        assert bp.hwm_ratio <= 0.99

    def test_initial_stats(self):
        bp = BackpressureManager(max_queue_size=10)
        stats = bp.get_stats()
        assert stats["enqueued"] == 0
        assert stats["dropped_oldest"] == 0
        assert stats["dropped_newest"] == 0
        assert stats["queue_size"] == 0


# ---------------------------------------------------------------------------
# Enqueue — normal path
# ---------------------------------------------------------------------------


class TestEnqueueNormal:
    @pytest.mark.asyncio
    async def test_basic_enqueue(self):
        bp = BackpressureManager(max_queue_size=10, drop_policy="drop_oldest")
        q: asyncio.Queue = _make_queue(maxsize=10)
        ev = _make_event()
        await bp.enqueue_event(ev, q)
        assert q.qsize() == 1
        assert bp.stats["enqueued"] == 1

    @pytest.mark.asyncio
    async def test_multiple_enqueue(self):
        bp = BackpressureManager(max_queue_size=10, drop_policy="drop_oldest")
        q: asyncio.Queue = _make_queue(maxsize=10)
        for i in range(5):
            await bp.enqueue_event(_make_event(i), q)
        assert q.qsize() == 5
        assert bp.stats["enqueued"] == 5

    @pytest.mark.asyncio
    async def test_queue_size_tracked(self):
        bp = BackpressureManager(max_queue_size=10, drop_policy="drop_oldest")
        q: asyncio.Queue = _make_queue(maxsize=10)
        await bp.enqueue_event(_make_event(), q)
        assert bp.queue_size == 1


# ---------------------------------------------------------------------------
# Drop-oldest policy
# ---------------------------------------------------------------------------


class TestDropOldest:
    @pytest.mark.asyncio
    async def test_oldest_dropped_when_full(self):
        bp = BackpressureManager(max_queue_size=2, drop_policy="drop_oldest")
        q: asyncio.Queue = _make_queue(maxsize=2)
        await bp.enqueue_event(_make_event(1), q)
        await bp.enqueue_event(_make_event(2), q)
        # Queue is full — next enqueue should drop oldest
        await bp.enqueue_event(_make_event(3), q)
        assert q.qsize() == 2
        assert bp.stats["dropped_oldest"] == 1
        assert bp.stats["enqueued"] == 3
        # Oldest (1) was dropped; 2 and 3 remain
        items = []
        while not q.empty():
            items.append(q.get_nowait()._id)
        assert items == [2, 3]


# ---------------------------------------------------------------------------
# Drop-newest policy
# ---------------------------------------------------------------------------


class TestDropNewest:
    @pytest.mark.asyncio
    async def test_newest_dropped_when_full(self):
        bp = BackpressureManager(max_queue_size=2, drop_policy="drop_newest")
        q: asyncio.Queue = _make_queue(maxsize=2)
        await bp.enqueue_event(_make_event(1), q)
        await bp.enqueue_event(_make_event(2), q)
        # Queue full — newest (3) should be dropped
        await bp.enqueue_event(_make_event(3), q)
        assert q.qsize() == 2
        assert bp.stats["dropped_newest"] == 1
        assert bp.stats["enqueued"] == 2
        # 1 and 2 remain
        items = []
        while not q.empty():
            items.append(q.get_nowait()._id)
        assert items == [1, 2]


# ---------------------------------------------------------------------------
# Block policy
# ---------------------------------------------------------------------------


class TestBlockPolicy:
    @pytest.mark.asyncio
    async def test_block_timeout_drops_newest(self):
        bp = BackpressureManager(
            max_queue_size=1,
            drop_policy="block",
            block_timeout=0.05,
        )
        q: asyncio.Queue = _make_queue(maxsize=1)
        await bp.enqueue_event(_make_event(1), q)
        # Queue full; blocking will time out
        await bp.enqueue_event(_make_event(2), q)
        assert bp.stats["dropped_newest"] == 1
        assert q.qsize() == 1


# ---------------------------------------------------------------------------
# Critical events — never dropped
# ---------------------------------------------------------------------------


class TestCriticalEvents:
    @pytest.mark.asyncio
    async def test_critical_never_dropped(self):
        bp = BackpressureManager(
            max_queue_size=1,
            drop_policy="drop_newest",
            is_critical_event=lambda _e: True,
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=0)  # unbounded for await put
        await bp.enqueue_event(_make_event(1), q)
        assert bp.stats["critical_events"] == 1
        assert bp.stats["enqueued"] == 1

    @pytest.mark.asyncio
    async def test_critical_counter(self):
        calls = []

        def is_crit(ev):
            calls.append(ev)
            return ev._id == 2

        bp = BackpressureManager(
            max_queue_size=10,
            drop_policy="drop_oldest",
            is_critical_event=is_crit,
        )
        q: asyncio.Queue = _make_queue(maxsize=10)
        await bp.enqueue_event(_make_event(1), q)
        await bp.enqueue_event(_make_event(2), q)
        assert bp.stats["critical_events"] == 1
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# High-watermark detection
# ---------------------------------------------------------------------------


class TestHighWatermark:
    @pytest.mark.asyncio
    async def test_hwm_hit_recorded(self):
        bp = BackpressureManager(
            max_queue_size=4,
            drop_policy="drop_oldest",
            hwm_ratio=0.5,
        )
        q: asyncio.Queue = _make_queue(maxsize=4)
        # Fill to 50 % = 2/4
        await bp.enqueue_event(_make_event(1), q)
        await bp.enqueue_event(_make_event(2), q)
        # Third event triggers HWM (qsize 2 / 4 = 0.5 >= hwm_ratio)
        await bp.enqueue_event(_make_event(3), q)
        assert bp.stats["high_watermark_hits"] >= 1


# ---------------------------------------------------------------------------
# Rate-window tracking
# ---------------------------------------------------------------------------


class TestRateWindow:
    def test_trim_recent_window(self):
        bp = BackpressureManager(max_queue_size=10, rate_window_seconds=60)
        # Manually inject old timestamps
        bp._recent_enqueued.append(time.monotonic() - 120)
        bp._recent_enqueued.append(time.monotonic())
        bp.trim_recent_window()
        assert len(bp._recent_enqueued) == 1

    def test_rate_window_clamped_low(self):
        bp = BackpressureManager(max_queue_size=10, rate_window_seconds=1)
        assert bp._rate_window_seconds >= 10

    def test_rate_window_clamped_high(self):
        bp = BackpressureManager(max_queue_size=10, rate_window_seconds=9999)
        assert bp._rate_window_seconds <= 600


# ---------------------------------------------------------------------------
# Snapshot & stats
# ---------------------------------------------------------------------------


class TestSnapshotAndStats:
    @pytest.mark.asyncio
    async def test_get_stats_keys(self):
        bp = BackpressureManager(max_queue_size=10)
        q: asyncio.Queue = _make_queue(maxsize=10)
        await bp.enqueue_event(_make_event(), q)
        stats = bp.get_stats()
        assert "enqueued" in stats
        assert "queue_size" in stats
        assert stats["enqueued"] == 1

    def test_get_snapshot_keys(self):
        bp = BackpressureManager(max_queue_size=10)
        snap = bp.get_snapshot(started_at=time.monotonic() - 10)
        expected_keys = {
            "enqueued",
            "dropped_oldest",
            "dropped_newest",
            "high_watermark_hits",
            "critical_events",
            "critical_queue_blocked",
            "queue_size",
            "max_queue_size",
            "uptime_seconds",
            "rate_window_seconds",
            "events_window_count",
            "drops_window_count",
            "events_per_minute",
            "drops_per_minute",
            "queue_utilization_pct",
        }
        assert expected_keys.issubset(snap.keys())

    def test_uptime_reasonable(self):
        bp = BackpressureManager(max_queue_size=10)
        snap = bp.get_snapshot(started_at=time.monotonic() - 5)
        assert snap["uptime_seconds"] >= 4

    def test_queue_utilization(self):
        bp = BackpressureManager(max_queue_size=100)
        bp.queue_size = 50
        snap = bp.get_snapshot(started_at=time.monotonic())
        assert snap["queue_utilization_pct"] == 50

    def test_zero_max_queue_utilization(self):
        bp = BackpressureManager(max_queue_size=0)
        snap = bp.get_snapshot(started_at=time.monotonic())
        assert snap["queue_utilization_pct"] == 0
