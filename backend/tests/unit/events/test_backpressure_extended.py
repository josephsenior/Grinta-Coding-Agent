"""Comprehensive tests for backend.events.backpressure module.

Tests BackpressureManager queue policies, stats tracking, rate windows,
snapshot generation, and critical event handling.
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.events.backpressure import BackpressureManager
from backend.events.event import Event


def _make_event() -> MagicMock:
    """Create a mock Event for testing."""
    return MagicMock(spec=Event)


class TestBackpressureManagerInit(unittest.TestCase):
    """Tests for BackpressureManager initialization."""

    def test_default_init(self):
        mgr = BackpressureManager()
        self.assertGreater(mgr.max_queue_size, 0)
        self.assertIn(mgr.drop_policy, {"drop_oldest", "drop_newest", "block"})
        self.assertGreaterEqual(mgr.hwm_ratio, 0.1)
        self.assertLessEqual(mgr.hwm_ratio, 0.99)

    def test_custom_max_queue_size(self):
        mgr = BackpressureManager(max_queue_size=100)
        self.assertEqual(mgr.max_queue_size, 100)

    def test_custom_drop_policy(self):
        for policy in ("drop_oldest", "drop_newest", "block"):
            mgr = BackpressureManager(drop_policy=policy)
            self.assertEqual(mgr.drop_policy, policy)

    def test_invalid_drop_policy_defaults(self):
        mgr = BackpressureManager(drop_policy="invalid_policy")
        self.assertEqual(mgr.drop_policy, "drop_oldest")

    def test_hwm_ratio_clamped_low(self):
        mgr = BackpressureManager(hwm_ratio=0.01)
        self.assertEqual(mgr.hwm_ratio, 0.1)

    def test_hwm_ratio_clamped_high(self):
        mgr = BackpressureManager(hwm_ratio=1.5)
        self.assertEqual(mgr.hwm_ratio, 0.99)

    def test_hwm_ratio_valid(self):
        mgr = BackpressureManager(hwm_ratio=0.75)
        self.assertEqual(mgr.hwm_ratio, 0.75)

    def test_block_timeout(self):
        mgr = BackpressureManager(block_timeout=5.0)
        self.assertEqual(mgr.block_timeout, 5.0)

    def test_rate_window_clamped(self):
        mgr = BackpressureManager(rate_window_seconds=5)
        self.assertEqual(mgr._rate_window_seconds, 10)
        mgr2 = BackpressureManager(rate_window_seconds=1000)
        self.assertEqual(mgr2._rate_window_seconds, 600)

    def test_initial_stats(self):
        mgr = BackpressureManager()
        self.assertEqual(mgr.stats["enqueued"], 0)
        self.assertEqual(mgr.stats["dropped_oldest"], 0)
        self.assertEqual(mgr.stats["dropped_newest"], 0)
        self.assertEqual(mgr.stats["high_watermark_hits"], 0)
        self.assertEqual(mgr.stats["critical_events"], 0)
        self.assertEqual(mgr.stats["critical_queue_blocked"], 0)
        self.assertEqual(mgr.queue_size, 0)

    def test_custom_critical_event_fn(self):
        fn = lambda e: True
        mgr = BackpressureManager(is_critical_event=fn)
        self.assertIs(mgr._is_critical_event, fn)


class TestBackpressureManagerEnqueue(unittest.IsolatedAsyncioTestCase):
    """Tests for enqueue_event with different policies."""

    async def test_enqueue_basic(self):
        mgr = BackpressureManager(max_queue_size=10, drop_policy="drop_oldest")
        queue = asyncio.Queue(maxsize=10)
        event = _make_event()

        await mgr.enqueue_event(event, queue)

        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(mgr.stats["enqueued"], 1)
        self.assertEqual(mgr.queue_size, 1)

    async def test_enqueue_multiple(self):
        mgr = BackpressureManager(max_queue_size=10, drop_policy="drop_oldest")
        queue = asyncio.Queue(maxsize=10)

        for _ in range(5):
            await mgr.enqueue_event(_make_event(), queue)

        self.assertEqual(queue.qsize(), 5)
        self.assertEqual(mgr.stats["enqueued"], 5)

    async def test_drop_oldest_when_full(self):
        mgr = BackpressureManager(max_queue_size=3, drop_policy="drop_oldest")
        queue = asyncio.Queue(maxsize=3)

        # Fill the queue
        for _ in range(3):
            await mgr.enqueue_event(_make_event(), queue)

        self.assertEqual(mgr.stats["enqueued"], 3)
        self.assertEqual(mgr.stats["dropped_oldest"], 0)

        # Enqueue one more → should drop oldest
        await mgr.enqueue_event(_make_event(), queue)

        self.assertEqual(mgr.stats["enqueued"], 4)
        self.assertEqual(mgr.stats["dropped_oldest"], 1)
        self.assertEqual(queue.qsize(), 3)

    async def test_drop_newest_when_full(self):
        mgr = BackpressureManager(max_queue_size=3, drop_policy="drop_newest")
        queue = asyncio.Queue(maxsize=3)

        # Fill the queue
        for _ in range(3):
            await mgr.enqueue_event(_make_event(), queue)

        # Enqueue one more → should drop newest (the new one)
        await mgr.enqueue_event(_make_event(), queue)

        self.assertEqual(mgr.stats["dropped_newest"], 1)
        self.assertEqual(queue.qsize(), 3)

    async def test_block_policy_success(self):
        mgr = BackpressureManager(
            max_queue_size=2, drop_policy="block", block_timeout=1.0
        )
        queue = asyncio.Queue(maxsize=2)

        # Fill the queue
        await mgr.enqueue_event(_make_event(), queue)
        await mgr.enqueue_event(_make_event(), queue)

        # Start a consumer that frees space
        async def consume():
            await asyncio.sleep(0.05)
            queue.get_nowait()
            queue.task_done()

        task = asyncio.create_task(consume())
        await mgr.enqueue_event(_make_event(), queue)
        await task

        self.assertEqual(mgr.stats["enqueued"], 3)
        self.assertEqual(mgr.stats["dropped_newest"], 0)

    async def test_block_policy_timeout(self):
        mgr = BackpressureManager(
            max_queue_size=1, drop_policy="block", block_timeout=0.05
        )
        queue = asyncio.Queue(maxsize=1)
        await queue.put(_make_event())

        mgr.stats["enqueued"] = 1  # Manually track first put

        # No consumer → will timeout
        await mgr.enqueue_event(_make_event(), queue)

        self.assertEqual(mgr.stats["dropped_newest"], 1)

    async def test_hwm_detection(self):
        mgr = BackpressureManager(
            max_queue_size=10, drop_policy="drop_oldest", hwm_ratio=0.5
        )
        queue = asyncio.Queue(maxsize=10)

        # Fill to 50% (5 items) to hit HWM ratio of 0.5
        for _ in range(5):
            await mgr.enqueue_event(_make_event(), queue)

        # The 6th event should trigger HWM hit (6/10 = 0.6 >= 0.5)
        await mgr.enqueue_event(_make_event(), queue)

        self.assertGreater(mgr.stats["high_watermark_hits"], 0)

    async def test_critical_event_never_dropped(self):
        mgr = BackpressureManager(
            max_queue_size=2,
            drop_policy="drop_newest",
            is_critical_event=lambda e: True,
        )
        queue = asyncio.Queue(maxsize=2)

        # Fill queue
        await mgr.enqueue_event(_make_event(), queue)
        await mgr.enqueue_event(_make_event(), queue)

        # Critical event should still go through (awaits put)
        async def consume():
            await asyncio.sleep(0.01)
            queue.get_nowait()
            queue.task_done()

        task = asyncio.create_task(consume())
        await mgr.enqueue_event(_make_event(), queue)
        await task

        self.assertEqual(mgr.stats["critical_events"], 3)
        self.assertEqual(mgr.stats["dropped_newest"], 0)

    async def test_critical_event_blocked_stat(self):
        mgr = BackpressureManager(
            max_queue_size=1,
            drop_policy="drop_newest",
            is_critical_event=lambda e: True,
        )
        queue = asyncio.Queue(maxsize=1)
        await queue.put(_make_event())
        mgr.stats["critical_events"] = 1

        # Critical event on full queue
        async def consume():
            await asyncio.sleep(0.01)
            queue.get_nowait()
            queue.task_done()

        task = asyncio.create_task(consume())
        await mgr.enqueue_event(_make_event(), queue)
        await task

        self.assertEqual(mgr.stats["critical_queue_blocked"], 1)


class TestBackpressureManagerRateWindow(unittest.TestCase):
    """Tests for rate window and trimming."""

    def test_trim_removes_stale(self):
        mgr = BackpressureManager(rate_window_seconds=60)
        now = time.monotonic()
        # Add old and new samples
        mgr._recent_enqueued.append(now - 120)  # Stale
        mgr._recent_enqueued.append(now - 30)   # Recent
        mgr._recent_enqueued.append(now)          # Current

        mgr.trim_recent_window()

        self.assertEqual(len(mgr._recent_enqueued), 2)

    def test_trim_empty_deque(self):
        mgr = BackpressureManager()
        mgr.trim_recent_window()  # Should not raise
        self.assertEqual(len(mgr._recent_enqueued), 0)


class TestBackpressureManagerSnapshot(unittest.TestCase):
    """Tests for snapshot generation."""

    def test_get_snapshot_keys(self):
        mgr = BackpressureManager(max_queue_size=100)
        started_at = time.monotonic() - 10.0
        snap = mgr.get_snapshot(started_at)

        expected_keys = {
            "enqueued", "dropped_oldest", "dropped_newest",
            "high_watermark_hits", "critical_events", "critical_queue_blocked",
            "queue_size", "max_queue_size", "uptime_seconds",
            "rate_window_seconds", "events_window_count", "drops_window_count",
            "events_per_minute", "drops_per_minute", "queue_utilization_pct",
        }
        for key in expected_keys:
            self.assertIn(key, snap)

    def test_get_snapshot_uptime(self):
        mgr = BackpressureManager()
        started_at = time.monotonic() - 5.0
        snap = mgr.get_snapshot(started_at)
        self.assertGreaterEqual(snap["uptime_seconds"], 4)

    def test_get_snapshot_utilization(self):
        mgr = BackpressureManager(max_queue_size=100)
        mgr.queue_size = 50
        snap = mgr.get_snapshot(time.monotonic())
        self.assertEqual(snap["queue_utilization_pct"], 50)

    def test_get_snapshot_zero_max_queue(self):
        mgr = BackpressureManager(max_queue_size=100)
        mgr.max_queue_size = 0
        snap = mgr.get_snapshot(time.monotonic())
        self.assertEqual(snap["queue_utilization_pct"], 0)

    def test_get_stats_minimal(self):
        mgr = BackpressureManager()
        stats = mgr.get_stats()
        self.assertIn("enqueued", stats)
        self.assertIn("queue_size", stats)
        self.assertEqual(stats["queue_size"], 0)


if __name__ == "__main__":
    unittest.main()
