from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.logger import FORGE_logger as logger

# Retry parameters for transient flush failures
_MAX_FLUSH_RETRIES = 3
_RETRY_BASE_DELAY = 0.1  # 100ms, doubles each retry

# Batch flush settings
_DEFAULT_BATCH_SIZE = 16  # max events per flush cycle
_BATCH_DRAIN_TIMEOUT = 0.02  # 20ms window to accumulate a batch


class FileStore(Protocol):
    def write(self, filename: str, content: str) -> None: ...


@dataclass(slots=True)
class PersistedEvent:
    """Payload handed to the durable writer thread."""

    event_id: int
    payload: dict[str, Any]
    filename: str
    cache_filename: str | None = None
    cache_contents: str | None = None


class DurableEventWriter:
    """Serializes and persists events in a dedicated thread to avoid blocking producers."""

    def __init__(
        self,
        file_store: FileStore,
        *,
        max_queue_size: int = 4096,
        put_timeout: float = 2.0,
    ) -> None:
        self._file_store = file_store
        self._queue: queue.Queue[PersistedEvent | None] = queue.Queue(
            maxsize=max_queue_size
        )
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._drops = 0
        self._errors = 0
        self._put_timeout = put_timeout

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run, name="forge-event-writer", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if not self._thread:
            return
        try:
            self._queue.join()
        except Exception:
            logger.warning(
                "DurableEventWriter: queue.join() failed during stop; pending events may be lost",
                exc_info=True,
            )
        self._stop_flag.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        self._thread = None

    @property
    def drop_count(self) -> int:
        """Number of events dropped due to queue saturation."""
        return self._drops

    @property
    def queue_depth(self) -> int:
        """Current number of events waiting to be flushed."""
        return self._queue.qsize()

    @property
    def error_count(self) -> int:
        """Number of persistence flush errors encountered."""
        return self._errors

    def enqueue(self, persisted_event: PersistedEvent) -> bool:
        if not self._thread or not self._thread.is_alive():
            return False
        try:
            # Block up to _put_timeout before dropping — gives the writer
            # thread a chance to drain under transient load spikes.
            self._queue.put(persisted_event, timeout=self._put_timeout)
            return True
        except queue.Full:
            self._drops += 1
            logger.warning(
                "DurableEventWriter queue full after %.1fs; dropped event id=%s filename=%s (total drops: %d)",
                self._put_timeout,
                persisted_event.event_id,
                persisted_event.filename,
                self._drops,
            )
            return False

    def _run(self) -> None:
        while not self._stop_flag.is_set():
            batch = self._drain_batch()
            if batch is None:
                # Sentinel received – shut down
                break
            if not batch:
                continue
            self._flush_batch(batch)

    # ------------------------------------------------------------------
    # Batch helpers
    # ------------------------------------------------------------------

    def _drain_batch(self) -> list[PersistedEvent] | None:
        """Drain up to ``_DEFAULT_BATCH_SIZE`` events from the queue.

        Returns ``None`` when the sentinel (stop) value is received, an empty
        list when the queue was idle, or a non-empty list of events to flush.
        """
        batch: list[PersistedEvent] = []

        # Block on the first item so we don't spin-wait
        try:
            first = self._queue.get(timeout=0.1)
        except queue.Empty:
            return batch  # empty – caller will loop
        if first is None:
            self._queue.task_done()
            return None  # sentinel
        batch.append(first)

        # Opportunistically drain more items within a short window
        deadline = time.monotonic() + _BATCH_DRAIN_TIMEOUT
        while len(batch) < _DEFAULT_BATCH_SIZE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                break
            if item is None:
                self._queue.task_done()
                # Flush what we have, then tell caller to stop
                self._flush_batch(batch)
                return None
            batch.append(item)

        return batch

    def _flush_batch(self, batch: list[PersistedEvent]) -> None:
        """Flush all events in *batch*, retrying each individually on failure."""
        for item in batch:
            try:
                self._flush_with_retry(item)
            except Exception as exc:  # pragma: no cover - persistence must not crash thread
                self._errors += 1
                logger.error(
                    "Permanently failed to persist event id=%s filename=%s after %d retries: %s",
                    item.event_id,
                    item.filename,
                    _MAX_FLUSH_RETRIES,
                    exc,
                )
            finally:
                self._queue.task_done()

    def _flush_with_retry(self, persisted_event: PersistedEvent) -> None:
        """Attempt to flush an event with exponential-backoff retry on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_FLUSH_RETRIES):
            try:
                self._flush_event(persisted_event)
                return  # success
            except Exception as exc:
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Flush attempt %d/%d failed for event id=%s: %s (retrying in %.1fs)",
                    attempt + 1,
                    _MAX_FLUSH_RETRIES,
                    persisted_event.event_id,
                    exc,
                    delay,
                )
                if self._stop_flag.wait(delay):
                    # Stop requested during retry wait
                    break
        # All retries exhausted — propagate to caller
        if last_exc is not None:
            raise last_exc

    def _flush_event(self, persisted_event: PersistedEvent) -> None:
        serialized = json.dumps(persisted_event.payload)
        self._file_store.write(persisted_event.filename, serialized)
        if (
            persisted_event.cache_filename
            and persisted_event.cache_contents is not None
        ):
            try:
                self._file_store.write(
                    persisted_event.cache_filename, persisted_event.cache_contents
                )
            except Exception as exc:  # pragma: no cover - cache best effort
                logger.debug(
                    "Cache page write failed for event %s: %s",
                    persisted_event.event_id,
                    exc,
                )
