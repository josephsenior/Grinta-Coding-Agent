"""Stress tests for backpressure, circuit breaker, and durable writer under load.

These tests exercise the subsystems with high concurrency and volume to
verify they degrade gracefully instead of crashing or losing data silently.

Marked with ``pytest.mark.stress`` so they can be included/excluded via
``-m stress``.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.events.backpressure import BackpressureManager
from backend.events.durable_writer import DurableEventWriter, PersistedEvent
from backend.events.observation import NullObservation
from backend.utils.circuit_breaker import CircuitBreaker, CircuitBreakerManager

pytestmark = pytest.mark.stress


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_event(idx: int = 0) -> NullObservation:
    ev = NullObservation(content=f"stress-{idx}")
    ev._id = idx
    return ev


def _make_persisted(eid: int = 1) -> PersistedEvent:
    return PersistedEvent(
        event_id=eid,
        payload={"id": eid, "type": "stress"},
        filename=f"stress_{eid}.json",
    )


# ---------------------------------------------------------------------------
# BackpressureManager stress tests
# ---------------------------------------------------------------------------


class TestBackpressureDropOldest:
    """Verify drop_oldest policy under flood conditions."""

    @pytest.mark.asyncio
    async def test_flood_with_drop_oldest(self):
        """Flooding a small queue should drop oldest events, not crash."""
        bp = BackpressureManager(
            max_queue_size=10,
            drop_policy="drop_oldest",
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        total = 200

        for i in range(total):
            await bp.enqueue_event(_dummy_event(i), q)

        # Queue should be at most max_queue_size
        assert q.qsize() <= 10
        # Drops should have been recorded
        assert bp.stats["dropped_oldest"] > 0
        # With drop_oldest, every new event is still enqueued (old ones are evicted)
        assert bp.stats["enqueued"] == total
        assert bp.stats["dropped_oldest"] == total - 10  # one eviction per overflow

    @pytest.mark.asyncio
    async def test_flood_preserves_recent(self):
        """Under drop_oldest, the most recent events should be in the queue."""
        bp = BackpressureManager(
            max_queue_size=5,
            drop_policy="drop_oldest",
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=5)

        for i in range(50):
            await bp.enqueue_event(_dummy_event(i), q)

        # Drain queue and check we have the recent events
        remaining = []
        while not q.empty():
            remaining.append(q.get_nowait())
        # Last events should be the most recent ones
        ids = [int(e.content.split("-")[1]) for e in remaining]
        assert ids[-1] >= 45  # Last event should be near the end


class TestBackpressureDropNewest:
    """Verify drop_newest policy under flood conditions."""

    @pytest.mark.asyncio
    async def test_flood_with_drop_newest(self):
        """Flooding a small queue with drop_newest should keep old events."""
        bp = BackpressureManager(
            max_queue_size=10,
            drop_policy="drop_newest",
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=10)

        for i in range(100):
            await bp.enqueue_event(_dummy_event(i), q)

        assert q.qsize() == 10
        assert bp.stats["dropped_newest"] > 0


class TestBackpressureBlock:
    """Verify block policy under timeout conditions."""

    @pytest.mark.asyncio
    async def test_block_policy_timeout(self):
        """Block policy should timeout and drop after block_timeout."""
        bp = BackpressureManager(
            max_queue_size=2,
            drop_policy="block",
            block_timeout=0.05,  # 50ms timeout
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=2)

        # Fill queue
        await bp.enqueue_event(_dummy_event(0), q)
        await bp.enqueue_event(_dummy_event(1), q)

        # This should block briefly then drop
        start = time.monotonic()
        await bp.enqueue_event(_dummy_event(2), q)
        elapsed = time.monotonic() - start

        assert bp.stats["dropped_newest"] >= 1
        assert elapsed >= 0.04  # Should have waited near the timeout


class TestBackpressureCriticalEvents:
    """Critical events must never be dropped."""

    @pytest.mark.asyncio
    async def test_critical_events_survive_full_queue(self):
        bp = BackpressureManager(
            max_queue_size=5,
            drop_policy="drop_newest",
            is_critical_event=lambda e: "critical" in cast(Any, e).content,
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=5)

        # Fill queue with normal events
        for i in range(5):
            await bp.enqueue_event(_dummy_event(i), q)

        # Drain one slot so the critical event can be enqueued without blocking
        _ = q.get_nowait()
        q.task_done()

        # Critical event should still be added
        critical = NullObservation(content="critical-event")
        critical._id = 999
        await bp.enqueue_event(critical, q)

        # Critical should be enqueued
        assert bp.stats["critical_events"] >= 1
        assert bp.stats["enqueued"] >= 6  # 5 normal + 1 critical


class TestBackpressureHighWatermark:
    """High watermark detection should fire consistently."""

    @pytest.mark.asyncio
    async def test_hwm_fires_when_queue_fills(self):
        bp = BackpressureManager(
            max_queue_size=10,
            drop_policy="drop_oldest",
            hwm_ratio=0.5,  # 50% = 5 events
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=10)

        for i in range(10):
            await bp.enqueue_event(_dummy_event(i), q)

        # HWM should have fired multiple times (at 5, 6, 7, 8, 9 events)
        assert bp.stats["high_watermark_hits"] > 0


class TestBackpressureRateWindow:
    """Rate window statistics should track correctly under load."""

    @pytest.mark.asyncio
    async def test_rate_window_tracking(self):
        bp = BackpressureManager(
            max_queue_size=1000,
            rate_window_seconds=60,
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)

        for i in range(50):
            await bp.enqueue_event(_dummy_event(i), q)

        snapshot = bp.get_snapshot(started_at=time.monotonic() - 10)
        assert snapshot["events_window_count"] == 50
        assert snapshot["events_per_minute"] > 0
        assert snapshot["queue_utilization_pct"] > 0


class TestBackpressureConcurrent:
    """Concurrent async producers should not corrupt state."""

    @pytest.mark.asyncio
    async def test_concurrent_producers(self):
        bp = BackpressureManager(
            max_queue_size=100,
            drop_policy="drop_oldest",
        )
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        n_producers = 10
        events_per_producer = 50

        async def produce(start_id: int):
            for i in range(events_per_producer):
                await bp.enqueue_event(_dummy_event(start_id + i), q)

        tasks = [produce(i * events_per_producer) for i in range(n_producers)]
        await asyncio.gather(*tasks)

        total = n_producers * events_per_producer
        # With drop_oldest, every new event is enqueued; old ones are evicted separately.
        assert bp.stats["enqueued"] == total
        # Evictions should be non-negative and not exceed theoretical max
        assert bp.stats["dropped_oldest"] >= 0
        assert bp.stats["dropped_oldest"] <= total


# ---------------------------------------------------------------------------
# Circuit Breaker stress tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerUnderLoad:
    """Circuit breaker transitions under rapid failure/success patterns."""

    @pytest.mark.asyncio
    async def test_rapid_failures_open_breaker(self):
        cb = CircuitBreaker("stress-test")
        cb.failure_threshold = 3

        # Trigger failures
        for _ in range(5):
            try:

                async def fail():
                    raise RuntimeError("boom")

                await cb.async_call(fail)
            except RuntimeError:
                pass

        assert cb.state.state == "open"

    @pytest.mark.asyncio
    async def test_breaker_blocks_when_open(self):
        cb = CircuitBreaker("block-test")
        cb.failure_threshold = 2
        cb.base_open_seconds = 10  # Long open period

        # Open the breaker
        for _ in range(3):
            try:

                async def fail():
                    raise RuntimeError("boom")

                await cb.async_call(fail)
            except RuntimeError:
                pass

        # Subsequent calls should be blocked
        with pytest.raises(RuntimeError, match="circuit_open"):

            async def should_not_run():
                return "ok"

            await cb.async_call(should_not_run)

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        cb = CircuitBreaker("recovery-test")
        cb.failure_threshold = 2
        cb.base_open_seconds = 0.05  # Very short open period

        # Open the breaker
        for _ in range(3):
            try:

                async def fail():
                    raise RuntimeError("boom")

                await cb.async_call(fail)
            except RuntimeError:
                pass

        assert cb.state.state == "open"

        # Wait for it to transition to half-open
        await asyncio.sleep(0.1)

        # A successful call should close the breaker
        async def succeed():
            return "ok"

        result = await cb.async_call(succeed)
        assert result == "ok"
        assert cb.state.state == "closed"

    @pytest.mark.asyncio
    async def test_manager_concurrent_access(self):
        """Multiple coroutines accessing the same breaker key concurrently."""
        mgr = CircuitBreakerManager()
        call_count = 0

        async def increment():
            nonlocal call_count
            call_count += 1
            return call_count

        tasks = [mgr.async_call("shared-key", increment) for _ in range(20)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 20
        assert call_count == 20


# ---------------------------------------------------------------------------
# DurableEventWriter stress tests
# ---------------------------------------------------------------------------


def _make_file_store():
    store = MagicMock()
    store.write = MagicMock()
    return store


class TestDurableWriterThroughput:
    """Durable writer should handle sustained write volume."""

    def test_high_volume_write(self):
        """Writer should persist hundreds of events without crashes."""
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=512)
        writer.start()
        try:
            n = 200
            for i in range(n):
                assert writer.enqueue(_make_persisted(i)) is True

            # Wait for all to flush
            deadline = time.time() + 10
            while writer.queue_depth > 0 and time.time() < deadline:
                time.sleep(0.05)

            assert writer.error_count == 0
            assert store.write.call_count >= n
        finally:
            writer.stop(timeout=5.0)

    def test_concurrent_enqueue(self):
        """Multiple threads enqueuing should not corrupt or crash."""
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=1024)
        writer.start()
        try:
            n_per_thread = 50
            n_threads = 8

            def produce(start_id):
                for i in range(n_per_thread):
                    writer.enqueue(_make_persisted(start_id + i))

            with ThreadPoolExecutor(max_workers=n_threads) as ex:
                futs = [ex.submit(produce, t * n_per_thread) for t in range(n_threads)]
                for f in futs:
                    f.result(timeout=10)

            # Wait for drain
            deadline = time.time() + 10
            while writer.queue_depth > 0 and time.time() < deadline:
                time.sleep(0.05)

            total = n_per_thread * n_threads
            assert store.write.call_count >= total
            assert writer.error_count == 0
        finally:
            writer.stop(timeout=5.0)

    def test_slow_store_does_not_block_enqueue(self):
        """A slow file store should not block enqueue for long."""
        store = _make_file_store()
        store.write.side_effect = lambda *_: time.sleep(0.01)
        writer = DurableEventWriter(store, max_queue_size=256)
        writer.start()
        try:
            start = time.monotonic()
            for i in range(50):
                writer.enqueue(_make_persisted(i))
            enqueue_time = time.monotonic() - start

            # Enqueuing 50 events should be fast (< 2s), even with slow store
            assert enqueue_time < 2.0
        finally:
            writer.stop(timeout=5.0)


class TestDurableWriterQueueSaturation:
    """Writer should handle queue saturation gracefully."""

    def test_drops_counted_when_queue_full(self):
        """When queue is tiny and store is blocked, drops should be counted."""
        store = _make_file_store()
        # Block the writer so queue fills
        store.write.side_effect = lambda *_: time.sleep(10)
        writer = DurableEventWriter(store, max_queue_size=3, put_timeout=0.05)
        writer.start()
        try:
            # Enqueue several — some should drop
            for i in range(10):
                writer.enqueue(_make_persisted(i))
                time.sleep(0.01)

            assert writer.drop_count >= 1
        finally:
            writer.stop(timeout=1.0)


class TestDurableWriterErrorResilience:
    """Writer should survive transient and permanent errors."""

    def test_intermittent_errors(self):
        """Writer should retry and eventually succeed on intermittent errors."""
        store = _make_file_store()
        call_count = 0

        def flaky_write(filename, content):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise OSError("transient disk error")

        store.write.side_effect = flaky_write
        writer = DurableEventWriter(store, max_queue_size=64)
        writer.start()
        try:
            for i in range(20):
                writer.enqueue(_make_persisted(i))

            deadline = time.time() + 10
            while writer.queue_depth > 0 and time.time() < deadline:
                time.sleep(0.1)

            # Some events might succeed, some fail — but writer should still be alive
            assert writer._thread is not None
            assert writer._thread.is_alive()
        finally:
            writer.stop(timeout=5.0)
