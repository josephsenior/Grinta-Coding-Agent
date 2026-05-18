from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.logger import app_logger as logger

# Retry parameters for transient flush failures
_MAX_FLUSH_RETRIES = 3
_RETRY_BASE_DELAY = 0.1  # 100ms, doubles each retry

# Batch flush settings
_DEFAULT_BATCH_SIZE = 16  # max events per flush cycle
_BATCH_DRAIN_TIMEOUT = 0.02  # 20ms window to accumulate a batch


class FileStore(Protocol):
    def write(self, filename: str, content: str) -> None: ...
    def delete(self, filename: str) -> None: ...


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
        max_queue_size: int = 2048,
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
        self._in_flight = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run, name='app-event-writer', daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0, drain_timeout: float = 30.0) -> None:
        if not self._thread:
            return

        # Signal the writer thread to stop after its current batch.
        self._stop_flag.set()

        # Best-effort drain: wait for in-flight items to complete while guarding
        # against negative counters (from double task_done() bugs in callers) and
        # orphaned sentinels that permanently suppress the counter above zero.
        deadline = time.monotonic() + drain_timeout
        last_remaining = self._queue.unfinished_tasks
        stall_count = 0
        while self._queue.unfinished_tasks > 0 and time.monotonic() < deadline:
            time.sleep(0.01)
            remaining = self._queue.unfinished_tasks
            if remaining >= last_remaining:
                stall_count += 1
            else:
                stall_count = 0
                last_remaining = remaining
            # Guard: counter stuck above zero due to orphaned sentinel or
            # negative counter from double task_done().  After 500 consecutive
            # iterations (~5s) with no progress, assume a structural issue
            # and exit rather than spin forever.
            if stall_count > 500:
                logger.warning(
                    'DurableEventWriter: drain stalled at %d unfinished tasks — '
                    'breaking drain loop to allow shutdown. '
                    'This usually indicates a queue counter inconsistency.',
                    remaining,
                )
                break
            # Also guard against negative counter (over-decremented): negative
            # means items are done, so exit the drain loop.
            if remaining < 0:
                logger.debug(
                    'DurableEventWriter: unfinished_tasks is %d — '
                    'counter below zero, exiting drain loop.',
                    remaining,
                )
                break

        remaining = self._queue.unfinished_tasks
        if remaining > 0:
            logger.warning(
                'DurableEventWriter: drain timeout after %.1fs with %d '
                'unfinished tasks — pending events may be lost',
                drain_timeout,
                remaining,
            )

        # Best-effort sentinel to wake the writer thread
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
        return self._queue.qsize() + self._in_flight

    @property
    def error_count(self) -> int:
        """Number of persistence flush errors encountered."""
        return self._errors

    def _pending_path(self, filename: str) -> str:
        return filename + '.pending'

    def enqueue(self, persisted_event: PersistedEvent) -> bool:
        if not self._thread or not self._thread.is_alive():
            return False

        # Write WAL marker BEFORE enqueueing so that a crash between WAL write
        # and enqueue is recoverable (the .pending file exists and will be
        # replayed on restart).  If the WAL write fails we still attempt to
        # enqueue — the event will be flushed but without crash-recovery
        # coverage for this event.
        serialized = json.dumps(persisted_event.payload)
        pending_path = self._pending_path(persisted_event.filename)
        wal_ok = False
        try:
            self._file_store.write(pending_path, serialized)
            wal_ok = True
        except Exception as exc:
            logger.error(
                'WAL: could not write .pending marker %s for event id=%d: %s. '
                'Event will still be enqueued but crash-recovery coverage for '
                'this event is reduced until flush completes.',
                pending_path,
                persisted_event.event_id,
                exc,
            )

        try:
            # Block up to _put_timeout before dropping — gives the writer
            # thread a chance to drain under transient load spikes.
            self._queue.put(persisted_event, timeout=self._put_timeout)
        except queue.Full:
            self._drops += 1
            logger.warning(
                'DurableEventWriter queue full after %.1fs; dropped event id=%s filename=%s (total drops: %d)',
                self._put_timeout,
                persisted_event.event_id,
                persisted_event.filename,
                self._drops,
            )
            # Clean up the WAL marker for the dropped event to prevent
            # a phantom recovery on restart.
            if wal_ok:
                try:
                    self._file_store.delete(pending_path)
                except Exception:
                    pass
            return False

        return wal_ok

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
        self._in_flight += 1
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
            self._in_flight += 1
            batch.append(item)

        return batch

    def _flush_batch(self, batch: list[PersistedEvent]) -> None:
        """Flush all events in *batch*, retrying each individually on failure."""
        for item in batch:
            try:
                self._flush_with_retry(item)
            except (
                Exception
            ) as exc:  # pragma: no cover - persistence must not crash thread
                self._errors += 1
                logger.error(
                    'Permanently failed to persist event id=%s filename=%s after %d retries: %s',
                    item.event_id,
                    item.filename,
                    _MAX_FLUSH_RETRIES,
                    exc,
                )
                # Clean up WAL marker — will be re-created if retried on restart
                pending_path = self._pending_path(item.filename)
                try:
                    self._file_store.delete(pending_path)
                except Exception as purge_exc:
                    logger.debug(
                        'WAL: could not clean up .pending after permanent failure %s: %s',
                        pending_path,
                        purge_exc,
                    )
            finally:
                # Decrement _in_flight BEFORE task_done() so that if task_done()
                # raises (e.g. from a double-call bug elsewhere), the counter is
                # still updated and the drain loop won't stall.
                if self._in_flight > 0:
                    self._in_flight -= 1
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
                    'Flush attempt %d/%d failed for event id=%s: %s (retrying in %.1fs)',
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

        # Remove WAL marker on successful flush — crash-recovery no longer needed.
        pending_path = self._pending_path(persisted_event.filename)
        try:
            self._file_store.delete(pending_path)
        except Exception as exc:
            logger.debug(
                'WAL: could not remove .pending marker %s: %s',
                pending_path,
                exc,
            )

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
                    'Cache page write failed for event %s: %s',
                    persisted_event.event_id,
                    exc,
                )
