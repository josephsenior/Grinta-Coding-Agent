"""Backpressure management for the EventStream delivery queue.

Encapsulates bounded-queue policy, high-watermark detection, rate-window
statistics, and the async enqueue path.  Used as a composition helper by
:class:`~backend.ledger.stream.EventStream`.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import Any, ClassVar

from backend.core.logger import app_logger as logger
from backend.ledger.config import get_event_runtime_defaults
from backend.ledger.event import Event


class BackpressureManager:
    """Manages queue backpressure, stats tracking and rate windows.

    Parameters
    ----------
    max_queue_size:
        Hard cap on the asyncio delivery queue.
    drop_policy:
        ``drop_oldest``, ``drop_newest``, or ``block``.
    hwm_ratio:
        Fraction of *max_queue_size* that triggers a high-watermark log.
    block_timeout:
        Seconds to wait when *drop_policy* is ``block``.
    rate_window_seconds:
        Sliding window size for per-minute rate counters.
    is_critical_event:
        Optional callable ``(Event) -> bool`` to classify critical events.
    """

    _DEFAULTS: ClassVar[dict[str, str]] = {
        "max_queue_size": "APP_EVENTSTREAM_MAX_QUEUE",
        "drop_policy": "APP_EVENTSTREAM_POLICY",
        "hwm_ratio": "APP_EVENTSTREAM_HWM_RATIO",
        "block_timeout": "APP_EVENTSTREAM_BLOCK_TIMEOUT",
        "rate_window_seconds": "APP_EVENTSTREAM_RATE_WINDOW_SECONDS",
    }

    def __init__(
        self,
        *,
        max_queue_size: int | None = None,
        drop_policy: str | None = None,
        hwm_ratio: float | None = None,
        block_timeout: float | None = None,
        rate_window_seconds: int | None = None,
        is_critical_event: Callable[[Event], bool] | None = None,
    ) -> None:
        defaults = get_event_runtime_defaults()
        self.max_queue_size = (
            max_queue_size
            if max_queue_size is not None
            else int(defaults.max_queue_size)
        )
        _policy = (
            drop_policy if drop_policy is not None else defaults.drop_policy
        ).lower()
        self.drop_policy = (
            _policy
            if _policy in {"drop_oldest", "drop_newest", "block"}
            else "drop_oldest"
        )
        self.hwm_ratio = max(
            0.1,
            min(
                0.99,
                float(hwm_ratio if hwm_ratio is not None else defaults.hwm_ratio),
            ),
        )
        self.block_timeout = float(
            block_timeout if block_timeout is not None else defaults.block_timeout
        )
        self._is_critical_event = is_critical_event or (lambda _e: False)

        # ---- stats ----------------------------------------------------------
        self.stats: dict[str, int] = {
            "enqueued": 0,
            "dropped_oldest": 0,
            "dropped_newest": 0,
            "high_watermark_hits": 0,
            "critical_events": 0,
            "critical_queue_blocked": 0,
        }
        self._rate_window_seconds: int = 60
        try:
            raw = (
                rate_window_seconds
                if rate_window_seconds is not None
                else int(defaults.rate_window_seconds)
            )
            self._rate_window_seconds = max(10, min(600, int(raw)))
        except Exception:
            self._rate_window_seconds = 60

        # maxlen is a safety net; trim_recent_window() is the primary bound.
        self._recent_enqueued: deque[float] = deque(maxlen=10_000)
        self._recent_drops: deque[float] = deque(maxlen=10_000)
        self.queue_size: int = 0

    # ------------------------------------------------------------------
    # Rate-window helpers
    # ------------------------------------------------------------------

    def trim_recent_window(self) -> None:
        """Prune stale samples from the sliding rate windows."""
        cutoff = time.monotonic() - self._rate_window_seconds
        for samples in (self._recent_enqueued, self._recent_drops):
            while samples and samples[0] < cutoff:
                samples.popleft()

    def _record_recent(self, samples: deque[float]) -> None:
        samples.append(time.monotonic())
        self.trim_recent_window()

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def get_snapshot(self, started_at: float) -> dict[str, int]:
        """Return a dict of backpressure counters for health checks."""
        self.trim_recent_window()
        snap: dict[str, int] = dict(self.stats)
        snap["queue_size"] = self.queue_size
        snap["max_queue_size"] = self.max_queue_size
        snap["uptime_seconds"] = int(max(0.0, time.monotonic() - started_at))
        snap["rate_window_seconds"] = self._rate_window_seconds
        snap["events_window_count"] = len(self._recent_enqueued)
        snap["drops_window_count"] = len(self._recent_drops)
        if self._rate_window_seconds > 0:
            snap["events_per_minute"] = int(
                round(len(self._recent_enqueued) * 60 / self._rate_window_seconds)
            )
            snap["drops_per_minute"] = int(
                round(len(self._recent_drops) * 60 / self._rate_window_seconds)
            )
        else:
            snap["events_per_minute"] = 0
            snap["drops_per_minute"] = 0
        if self.max_queue_size > 0:
            snap["queue_utilization_pct"] = int(
                round((self.queue_size / self.max_queue_size) * 100)
            )
        else:
            snap["queue_utilization_pct"] = 0
        return snap

    def get_stats(self) -> dict[str, int]:
        """Return a minimal snapshot for monitoring / tests."""
        out = dict(self.stats)
        out["queue_size"] = self.queue_size
        return out

    # ------------------------------------------------------------------
    # Enqueue with backpressure
    # ------------------------------------------------------------------

    async def enqueue_event(
        self,
        event: Event,
        queue: asyncio.Queue[Any],
    ) -> None:
        """Put *event* into *queue* respecting the configured policy."""
        is_critical = self._is_critical_event(event)
        if is_critical:
            self.stats["critical_events"] += 1

        if self._is_above_high_watermark(queue):
            self.stats["high_watermark_hits"] += 1
            logger.debug(
                "EventStream queue high-watermark: size=%s max=%s policy=%s",
                queue.qsize(),
                self.max_queue_size,
                self.drop_policy,
            )

        if is_critical:
            await self._enqueue_critical(event, queue)
            return

        if queue.full():
            await self._handle_full_queue(event, queue)
            return

        await queue.put(event)
        self.stats["enqueued"] += 1
        self._record_recent(self._recent_enqueued)
        self.queue_size = queue.qsize()

    def _is_above_high_watermark(self, queue: asyncio.Queue[Any]) -> bool:
        return (
            self.max_queue_size > 0
            and queue.qsize() / self.max_queue_size >= self.hwm_ratio
        )

    async def _enqueue_critical(self, event: Event, queue: asyncio.Queue[Any]) -> None:
        if queue.full():
            self.stats["critical_queue_blocked"] += 1
        await queue.put(event)
        self.stats["enqueued"] += 1
        self._record_recent(self._recent_enqueued)
        self.queue_size = queue.qsize()

    async def _handle_full_queue(
        self, event: Event, queue: asyncio.Queue[Any]
    ) -> None:
        if self.drop_policy == "drop_oldest":
            self._try_drop_oldest_and_put(event, queue)
            return
        if self.drop_policy == "block":
            await self._try_block_and_put(event, queue)
            return
        self.stats["dropped_newest"] += 1
        self._record_recent(self._recent_drops)
        logger.warning("EventStream full; dropped newest")

    def _try_drop_oldest_and_put(
        self, event: Event, queue: asyncio.Queue[Any]
    ) -> None:
        try:
            _ = queue.get_nowait()
            queue.task_done()
            self.stats["dropped_oldest"] += 1
            self._record_recent(self._recent_drops)
            queue.put_nowait(event)
            self.stats["enqueued"] += 1
            self._record_recent(self._recent_enqueued)
        except asyncio.QueueEmpty:
            self.stats["dropped_newest"] += 1
            self._record_recent(self._recent_drops)
            logger.warning("EventStream full; dropped newest (empty on get)")
        self.queue_size = queue.qsize()

    async def _try_block_and_put(
        self, event: Event, queue: asyncio.Queue[Any]
    ) -> None:
        try:
            await asyncio.wait_for(queue.put(event), timeout=self.block_timeout)
            self.stats["enqueued"] += 1
            self._record_recent(self._recent_enqueued)
        except TimeoutError:
            self.stats["dropped_newest"] += 1
            self._record_recent(self._recent_drops)
            logger.warning(
                "EventStream full after blocking %.3fs; dropped newest",
                self.block_timeout,
            )
        self.queue_size = queue.qsize()
