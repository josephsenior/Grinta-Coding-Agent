"""Event coalescing for the EventStream.

Coalesces rapid bursts of similar events (e.g., consecutive streaming
chunks or status updates) into a single event, reducing overhead for
subscribers and persistence without losing semantic information.

Usage::

    coalescer = EventCoalescer(window_ms=100, max_batch=20)
    # Before adding: check if the event should be coalesced
    if coalescer.should_coalesce(event):
        coalescer.absorb(event)
    else:
        coalescer.flush()  # emit accumulated event
        stream.add_event(event, source)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.ledger.event import Event


# Event types eligible for coalescing and how to merge them.
# NOTE: StreamingChunkAction is intentionally NOT here — each chunk must be
# dispatched individually so the frontend can display tokens as they arrive.
_COALESCE_TYPES: set[str] = {
    'AgentStateChangedObservation',
    'NullObservation',
    'ChangeAgentStateAction',
}


class CoalescedBatch:
    """Represents accumulated events of the same type waiting to be flushed."""

    __slots__ = ('events', 'first_ts', 'last_ts', 'event_type')

    def __init__(self, event: Event) -> None:
        self.events: list[Event] = [event]
        self.first_ts = time.monotonic()
        self.last_ts = self.first_ts
        self.event_type = type(event).__name__

    def add(self, event: Event) -> None:
        self.events.append(event)
        self.last_ts = time.monotonic()

    @property
    def size(self) -> int:
        return len(self.events)

    @property
    def age_ms(self) -> float:
        return (time.monotonic() - self.first_ts) * 1000


class EventCoalescer:
    """Coalesces rapid bursts of same-type events into batches.

    Parameters:
        window_ms: Maximum age of a batch before it's flushed.
        max_batch: Maximum events in a batch before auto-flush.
        coalesce_types: Event class names eligible for coalescing.
    """

    def __init__(
        self,
        window_ms: float = 100.0,
        max_batch: int = 20,
        coalesce_types: set[str] | None = None,
    ) -> None:
        self._window_ms = window_ms
        self._max_batch = max_batch
        self._coalesce_types = coalesce_types or _COALESCE_TYPES
        self._pending: dict[str, CoalescedBatch] = {}
        # Stats
        self._coalesced_count: int = 0
        self._flushed_count: int = 0

    def should_coalesce(self, event: Event) -> bool:
        """Return True if this event type is eligible for coalescing."""
        return type(event).__name__ in self._coalesce_types

    def absorb(self, event: Event) -> Event | None:
        """Add an event to the pending batch.

        Returns:
            The representative event to emit if the batch is full
            (auto-flush), or ``None`` if still accumulating.
        """
        event_type = type(event).__name__
        batch = self._pending.get(event_type)

        if batch is None:
            self._pending[event_type] = CoalescedBatch(event)
            return None

        batch.add(event)
        self._coalesced_count += 1

        # Auto-flush on batch size
        if batch.size >= self._max_batch:
            return self._flush_batch(event_type)

        # Auto-flush on window expiry
        if batch.age_ms >= self._window_ms:
            return self._flush_batch(event_type)

        return None

    def flush_all(self) -> list[Event]:
        """Flush all pending batches.

        Returns a list of representative events (one per batch).
        """
        results: list[Event] = []
        for event_type in list(self._pending):
            ev = self._flush_batch(event_type)
            if ev:
                results.append(ev)
        return results

    def flush_expired(self) -> list[Event]:
        """Flush only batches that have exceeded the coalescing window."""
        results: list[Event] = []
        for event_type in list(self._pending):
            batch = self._pending.get(event_type)
            if batch and batch.age_ms >= self._window_ms:
                ev = self._flush_batch(event_type)
                if ev:
                    results.append(ev)
        return results

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot."""
        return {
            'pending_batches': len(self._pending),
            'pending_events': sum(b.size for b in self._pending.values()),
            'coalesced_total': self._coalesced_count,
            'flushed_total': self._flushed_count,
            'window_ms': self._window_ms,
            'max_batch': self._max_batch,
        }

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _flush_batch(self, event_type: str) -> Event | None:
        """Flush a batch and return the representative event."""
        batch = self._pending.pop(event_type, None)
        if not batch or not batch.events:
            return None

        self._flushed_count += 1

        # For streaming chunks: use the latest event (it has accumulated content)
        if event_type == 'StreamingChunkAction':
            return self._merge_streaming_chunks(batch)

        # For state changes: use the latest state
        # For other types: use the last event (most recent)
        return batch.events[-1]

    def _merge_streaming_chunks(self, batch: CoalescedBatch) -> Event:
        """Merge streaming chunk events into a single representative event."""
        return batch.events[-1]
        # StreamingChunkAction has 'accumulated' field — the last event
        # already contains all accumulated content. Return it directly.
