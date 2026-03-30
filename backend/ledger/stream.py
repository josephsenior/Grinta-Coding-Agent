"""Event stream implementation with pub/sub and persistence helpers.

Backpressure is delegated to :mod:`backend.ledger.backpressure` and durable
persistence / WAL recovery to :mod:`backend.ledger.persistence`.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, cast

from backend.core.logger import app_logger as logger
from backend.ledger.backpressure import BackpressureManager
from backend.ledger.coalescing import EventCoalescer
from backend.ledger.config import get_event_runtime_defaults
from backend.ledger.event import Event, EventSource
from backend.ledger.event_store import EventStore
from backend.ledger.persistence import EventPersistence
from backend.ledger.secret_masker import SecretMasker
from backend.ledger.serialization.event import event_from_dict, event_to_dict
from backend.persistence.locations import get_conversation_dir
from backend.utils.async_utils import call_sync_from_async, run_or_schedule
if TYPE_CHECKING:
    from backend.persistence import FileStore


class EventStreamSubscriber(str, Enum):
    """Lightweight wrapper attaching callbacks to event stream broadcast queue."""

    AGENT_CONTROLLER = "agent_controller"
    CLI = "cli"
    SERVER = "server"
    RUNTIME = "runtime"
    MEMORY = "memory"
    MAIN = "main"
    TEST = "test"


async def session_exists(
    sid: str, file_store: FileStore, user_id: str | None = None
) -> bool:
    """Check if a session exists in file storage.

    Args:
        sid: Session ID to check
        file_store: File storage backend
        user_id: Optional user ID for scoping

    Returns:
        True if session directory exists

    """
    try:
        await call_sync_from_async(file_store.list, get_conversation_dir(sid, user_id))
        return True
    except FileNotFoundError:
        return False


def _warn_unclosed_stream(sid: str) -> None:
    """weakref.finalize callback — fires if a stream is GC'd without close()."""
    message = "EventStream '%s' was GC'd without close(); resources may leak."
    try:
        logger.warning(message, sid)
    except (ValueError, OSError, AttributeError, BrokenPipeError):
        try:
            import sys

            s = getattr(sys, "stderr", None)
            if s is not None:
                s.write(f"{message % sid}\n")
        except (ValueError, OSError, AttributeError, BrokenPipeError):
            pass


class EventStream(EventStore):
    """Thread-safe event stream with pub/sub functionality.

    Extends EventStore with subscriber management and async event delivery.
    Events are queued and dispatched to subscribers in background threads
    with dedicated event loops for each callback.

    Heavy-lifting is delegated to composable helpers:

    * :class:`BackpressureManager` — queue sizing, stats, rate windows.
    * :class:`EventPersistence` — WAL, file writes, cache pages, SQLite.
    """

    secrets: dict[str, str]
    _subscribers: dict[str, dict[str, Callable]]
    _lock: threading.Lock
    _async_queue: asyncio.Queue[Event | object] | None
    _queue_thread: threading.Thread
    _queue_loop: asyncio.AbstractEventLoop | None
    _delivery_pool: ThreadPoolExecutor
    _workers: list[asyncio.Task[Any]]
    _stop_event: asyncio.Event | None
    _queue_ready: threading.Event
    _worker_count: int
    _stop_sentinel: object
    _write_page_cache: list[dict]
    _started_at_monotonic: float
    # Global weak registry for metrics aggregation
    _GLOBAL_STREAMS: ClassVar[weakref.WeakSet[EventStream]] = weakref.WeakSet()

    # EventStore instances are identity-based objects; keep hashability explicit so
    # WeakSet registration for global metrics works even if parent classes define
    # custom equality semantics.
    __hash__ = object.__hash__

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        user_id: str | None = None,
        *,
        max_queue_size: int | None = None,
        drop_policy: str | None = None,
        hwm_ratio: float | None = None,
        block_timeout: float | None = None,
        worker_count: int | None = None,
        async_write: bool | str | None = None,
    ) -> None:
        """Initialize event stream with subscriber management.

        Args:
            sid: Session ID for this event stream
            file_store: File storage backend for persisting events
            user_id: Optional user ID for scoping
            max_queue_size: Maximum in-memory delivery queue size
            drop_policy: Backpressure policy (drop_oldest, drop_newest, block)
            hwm_ratio: High-watermark ratio for queue pressure logging
            block_timeout: Timeout used when drop policy is block
            worker_count: Number of delivery workers
            async_write: Whether to use async durable persistence writer

        """
        super().__init__(sid, file_store, user_id)
        self._started_at_monotonic = time.monotonic()
        self._stop_flag = threading.Event()
        event_defaults = get_event_runtime_defaults()

        # ---- Composition: backpressure manager ----------------------------
        self._bp = BackpressureManager(
            max_queue_size=max_queue_size,
            drop_policy=drop_policy,
            hwm_ratio=hwm_ratio,
            block_timeout=block_timeout,
            is_critical_event=EventPersistence.is_critical_event,
        )

        # ---- Composition: persistence / WAL --------------------------------
        _async_write = str(
            async_write if async_write is not None else event_defaults.async_write
        ).lower() in (
            "1",
            "true",
            "yes",
        )

        self._persist = EventPersistence(
            sid,
            file_store,
            user_id,
            async_write=_async_write,
            get_filename_for_id=self._get_filename_for_id,
            get_filename_for_cache=self._get_filename_for_cache,
            cache_size=self.cache_size,
            recent_persist_failures=deque(),
        )

        # ---- Queue / threading setup --------------------------------------
        self._queue_loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[Event | object] | None = None
        self._queue_ready = threading.Event()
        self._worker_count = max(
            1,
            int(worker_count if worker_count is not None else event_defaults.workers),
        )
        self._delivery_pool = ThreadPoolExecutor(max_workers=self._worker_count)
        self._workers: list[asyncio.Task[Any]] = []
        self._stop_event: asyncio.Event | None = None
        self._stop_sentinel = object()
        self._queue_thread = threading.Thread(target=self._run_queue_loop, daemon=True)
        self._queue_thread.start()

        # ---- Subscribers / secrets -----------------------------------------
        self._subscribers = {}
        self._lock = threading.Lock()
        self._secret_masker = SecretMasker()
        self.secrets = self._secret_masker.secrets
        self._activity_listeners: dict[str, Callable[[str], None]] = {}
        self._activity_listener_lock = threading.RLock()
        self._activity_listener_seq = 0
        self._write_page_cache: list[dict] = []

        # Register for global metrics aggregation
        try:  # pragma: no cover - defensive
            EventStream._GLOBAL_STREAMS.add(self)
        except Exception:
            logger.warning(
                "Failed to register EventStream for global metrics", exc_info=True
            )

        # Safety finalizer — ensures close() is called if the stream is GC'd
        # without an explicit close().  weakref.finalize is safe: it won't
        # prevent GC and fires exactly once.
        self._finalizer = weakref.finalize(self, _warn_unclosed_stream, self.sid)

        # Replay any incomplete writes from a previous crash
        self._persist.replay_pending_events()

        # ---- Event coalescing (opt-in via env var) -------------------------
        _coalesce = bool(event_defaults.coalesce)
        self._coalescer: EventCoalescer | None = (
            EventCoalescer(
                window_ms=event_defaults.coalesce_window_ms,
                max_batch=event_defaults.coalesce_max_batch,
            )
            if _coalesce
            else None
        )
        # If WAL replay recovered events, reset cur_id from disk
        if self._persist.stats.get("persist_failures", 0) == 0:
            self._cur_id = None

    def close(self) -> None:
        """Close event stream, stopping queue processing and cleaning up subscribers."""
        # Detach safety finalizer — we're closing explicitly.
        if hasattr(self, "_finalizer"):
            self._finalizer.detach()
        self._stop_flag.set()
        if self._queue_loop and self._stop_event:
            future = asyncio.run_coroutine_threadsafe(
                self._initiate_shutdown(), self._queue_loop
            )
            try:
                future.result(timeout=5)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Error shutting down event queue: %s", exc)
        if self._queue_thread.is_alive():
            # Never block forever during teardown; the thread is daemonized.
            self._queue_thread.join(timeout=5)
            if self._queue_thread.is_alive():
                logger.debug(
                    "EventStream '%s' queue thread did not stop within timeout; continuing",
                    self.sid,
                )
        self._subscribers.clear()
        self._activity_listeners.clear()
        self._persist.close()

    def get_backpressure_snapshot(self) -> dict[str, int]:
        """Return a lightweight snapshot of enqueue/drop stats.

        Intended for health classification in long-running sessions.
        """
        snapshot = self._bp.get_snapshot(self._started_at_monotonic)
        # Merge persistence stats
        snapshot.update(self._persist.stats)
        snapshot.update(self._persist.get_health_snapshot())
        snapshot["persist_failures_window_count"] = int(
            len(self._persist._recent_persist_failures)
        )
        if snapshot.get("rate_window_seconds", 0) > 0:
            rw = snapshot["rate_window_seconds"]
            snapshot["persist_failures_per_minute"] = int(
                round(len(self._persist._recent_persist_failures) * 60 / rw)
            )
        else:
            snapshot["persist_failures_per_minute"] = 0
        dw = self._persist.durable_writer
        if dw:
            snapshot["durable_writer_drops"] = int(dw.drop_count)
            snapshot["durable_writer_queue_depth"] = int(dw.queue_depth)
            snapshot["durable_writer_errors"] = int(dw.error_count)
        return snapshot

    def get_stats(self) -> dict[str, int]:
        """Return snapshot of backpressure stats for monitoring/tests."""
        out = self._bp.get_stats()
        out.update(self._persist.stats)
        return out

    @classmethod
    def iter_global_streams(cls) -> list[EventStream]:
        """Return a snapshot list of all live EventStream instances."""
        try:
            return list(cls._GLOBAL_STREAMS)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("iter_global_streams failed: %s", exc)
            return []

    def _clean_up_subscriber(self, subscriber_id: str, callback_id: str) -> None:
        """Clean up a specific subscriber callback."""
        if subscriber_id not in self._subscribers:
            logger.warning("Subscriber not found during cleanup: %s", subscriber_id)
            return
        if callback_id not in self._subscribers[subscriber_id]:
            logger.warning("Callback not found during cleanup: %s", callback_id)
            return

        del self._subscribers[subscriber_id][callback_id]
        if not self._subscribers[subscriber_id]:
            del self._subscribers[subscriber_id]

    def subscribe(
        self,
        subscriber_id: EventStreamSubscriber,
        callback: Callable[[Event], None],
        callback_id: str,
    ) -> None:
        """Subscribe to event stream with a callback function.

        Args:
            subscriber_id: Unique subscriber identifier
            callback: Function to call for each event
            callback_id: Unique callback identifier within subscriber

        Raises:
            ValueError: If callback_id already exists for this subscriber

        """
        if subscriber_id not in self._subscribers:
            self._subscribers[subscriber_id] = {}
        if callback_id in self._subscribers[subscriber_id]:
            msg = f"Callback ID on subscriber {subscriber_id} already exists: {callback_id}"
            raise ValueError(msg)
        self._subscribers[subscriber_id][callback_id] = callback

    def unsubscribe(
        self, subscriber_id: EventStreamSubscriber, callback_id: str
    ) -> None:
        """Unsubscribe callback from event stream and clean up resources.

        Args:
            subscriber_id: Subscriber identifier
            callback_id: Callback identifier to remove

        """
        if subscriber_id not in self._subscribers:
            logger.warning("Subscriber not found during unsubscribe: %s", subscriber_id)
            return
        if callback_id not in self._subscribers[subscriber_id]:
            logger.warning("Callback not found during unsubscribe: %s", callback_id)
            return
        self._clean_up_subscriber(subscriber_id, callback_id)

    def add_event(self, event: Event, source: EventSource) -> None:
        """Add event to stream with automatic ID assignment and persistence."""
        if self._should_drop_due_to_shutdown(event, source):
            return

        # Optional event coalescing for high-frequency event types
        if self._coalescer and self._coalescer.should_coalesce(event):
            merged = self._coalescer.absorb(event)
            if merged is None:
                return  # Still accumulating; event deferred
            event = merged  # Use the merged representative event

        self._ensure_event_can_be_added(event)
        event.timestamp = datetime.now()
        event.source = source

        sanitized_event, payload, cache_page_data = self._serialize_and_cache_event(
            event
        )
        cache_payload = self._persist.build_cache_payload(cache_page_data)

        # Persistence happens outside the lock intentionally: each event is
        # written to its own file keyed by ID, so concurrent writes to
        # different IDs are safe.  On WAL replay events are re-sorted by ID,
        # so transient out-of-order flushes do not cause ordering bugs.
        if sanitized_event.id is not None:
            self._persist.persist_event(payload, sanitized_event.id, cache_payload)

        if source == EventSource.USER:
            self._dispatch_event_inline(sanitized_event)
        else:
            self._enqueue_serialized_event(sanitized_event)
        self._notify_activity_listeners()

    def _dispatch_event_inline(self, event: Event) -> None:
        """Deliver a critical event immediately to current subscribers.

        User-originated events are part of the control plane: if they were to
        depend solely on the background queue thread, a stale worker could
        persist the message without ever waking the controller or echoing the
        UI. Inline delivery keeps that first hop deterministic while background
        delivery remains in place for the high-volume agent/environment stream.
        """
        callbacks = self._snapshot_subscribers()
        if not callbacks:
            return
        for subscriber_id, callback_id, callback in callbacks:
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    run_or_schedule(result)  # type: ignore[unreachable]
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error(
                    "Error in inline event callback %s for subscriber %s: %s",
                    callback_id,
                    subscriber_id,
                    exc,
                )

    def _should_drop_due_to_shutdown(self, event: Event, source: EventSource) -> bool:
        if not self._stop_flag.is_set():
            return False
        logger.debug(
            "EventStream closed; dropping event id=%s from source=%s",
            getattr(event, "id", None),
            source,
        )
        return True

    def _ensure_event_can_be_added(self, event: Event) -> None:
        evt_id = getattr(event, "id", Event.INVALID_ID)
        if not isinstance(evt_id, int):
            evt_id = Event.INVALID_ID
        if evt_id != Event.INVALID_ID:
            msg = (
                f"Event already has an ID:{evt_id}. It was probably added back to the "
                "EventStream from inside a handler, triggering a loop."
            )
            raise ValueError(msg)

    def _serialize_and_cache_event(
        self, event: Event
    ) -> tuple[Event, dict[str, Any], list[dict[str, Any]] | None]:
        from backend.ledger.action import (  # local import to avoid global cycle
            ChangeAgentStateAction,
        )

        cache_page_data: list[dict[str, Any]] | None = None

        with self._lock:
            event.id = self.cur_id
            event.sequence = self.cur_id
            self.cur_id += 1

        data = self._replace_secrets(event_to_dict(event))
        sanitized_event = event_from_dict(data)

        if isinstance(sanitized_event, ChangeAgentStateAction):
            logger.debug(
                "Queued ChangeAgentStateAction id=%s state=%s source=%s",
                sanitized_event.id,
                getattr(sanitized_event, "agent_state", None),
                sanitized_event.source,
            )

        with self._lock:
            current_write_page = self._write_page_cache
            current_write_page.append(data)
            if len(current_write_page) == self.cache_size:
                cache_page_data = current_write_page
                self._write_page_cache = []

        return sanitized_event, data, cache_page_data

    def _enqueue_serialized_event(self, event: Event) -> None:
        if not self._queue_ready.wait(timeout=2):
            logger.warning(
                "EventStream queue not ready; dropping event id=%s", event.id
            )
            return

        if not self._queue_loop or not self._async_queue:
            logger.warning(
                "EventStream queue loop missing; dropping event id=%s", event.id
            )
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._enqueue_event(event), self._queue_loop
            )
            future.result()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to enqueue event id=%s: %s", event.id, exc)

    def add_activity_listener(self, callback: Callable[[str], None]) -> str:
        """Register a callback invoked whenever a new event is added."""
        with self._activity_listener_lock:
            handle = f"listener-{self._activity_listener_seq}"
            self._activity_listener_seq += 1
            self._activity_listeners[handle] = callback
            return handle

    def remove_activity_listener(self, handle: str) -> None:
        with self._activity_listener_lock:
            self._activity_listeners.pop(handle, None)

    def _notify_activity_listeners(self) -> None:
        with self._activity_listener_lock:
            listeners = list(self._activity_listeners.values())
        for callback in listeners:
            try:
                callback(self.sid)
            except Exception as exc:
                logger.debug("Activity listener raised: %s", exc)

    def set_secrets(self, secrets: dict[str, str]) -> None:
        """Set secrets dictionary for masking sensitive values in events."""
        self._secret_masker.set_secrets(secrets)
        self.secrets = self._secret_masker.secrets

    def update_secrets(self, secrets: dict[str, str]) -> None:
        """Update secrets dictionary with additional values."""
        self._secret_masker.update_secrets(secrets)
        self.secrets = self._secret_masker.secrets

    def _replace_secrets(
        self, data: dict[str, Any], is_top_level: bool = True
    ) -> dict[str, Any]:
        """Delegate to SecretMasker for secret replacement."""
        return self._secret_masker.replace_secrets(data, is_top_level=is_top_level)

    def _run_queue_loop(self) -> None:
        """Start event loop in queue processing thread."""
        self._queue_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._queue_loop)
        self._async_queue = asyncio.Queue(maxsize=self._bp.max_queue_size)
        self._stop_event = asyncio.Event()
        self._workers = [
            self._queue_loop.create_task(self._worker_loop(worker_id))
            for worker_id in range(self._worker_count)
        ]
        self._queue_ready.set()
        try:
            self._queue_loop.run_until_complete(self._stop_event.wait())
        finally:
            for worker in self._workers:
                worker.cancel()
            self._queue_loop.run_until_complete(
                asyncio.gather(*self._workers, return_exceptions=True)
            )
            self._delivery_pool.shutdown(wait=True)
            self._queue_loop.close()

    async def _worker_loop(self, worker_id: int) -> None:
        """Consume events from the queue and dispatch them to subscribers."""
        if not self._async_queue:
            return
        queue = self._async_queue
        # Keep draining the queue even during shutdown so that
        # `_initiate_shutdown()` can reliably `await queue.join()`.
        while True:
            try:
                event = await queue.get()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error retrieving event from queue: %s", e)
                continue
            if event is self._stop_sentinel:
                queue.task_done()
                break
            try:
                if not self._stop_flag.is_set():
                    await self._dispatch_event(cast(Event, event))
            except Exception as e:
                logger.error("Error dispatching event: %s", e)
            finally:
                queue.task_done()
                self._bp.queue_size = queue.qsize()

    async def _dispatch_event(self, event: Event) -> None:
        """Dispatch a single event to all registered subscribers."""
        callbacks = self._snapshot_subscribers()
        if not callbacks:
            return
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(
                self._delivery_pool,
                self._execute_callback,
                callback,
                event,
                subscriber_id,
                callback_id,
            )
            for subscriber_id, callback_id, callback in callbacks
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _execute_callback(
        self,
        callback: Callable[[Event], Any],
        event: Event,
        subscriber_id: str,
        callback_id: str,
    ) -> None:
        """Execute subscriber callback inside thread pool with error handling."""
        try:
            result = callback(event)
            if inspect.isawaitable(result):
                asyncio.run(self._await_result(result))  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "Error in event callback %s for subscriber %s: %s",
                callback_id,
                subscriber_id,
                exc,
            )

    async def _await_result(self, awaitable: Any) -> None:
        """Await a coroutine returned from a synchronous callback wrapper."""
        await awaitable

    def _snapshot_subscribers(self) -> list[tuple[str, str, Callable[[Event], None]]]:
        """Create a snapshot of current subscribers to avoid holding locks."""
        with self._lock:
            return [
                (str(subscriber_id), callback_id, callback)
                for subscriber_id, callbacks in self._subscribers.items()
                for callback_id, callback in callbacks.items()
            ]

    async def _enqueue_event(self, event: Event) -> None:
        """Enqueue event with backpressure handling inside the event loop."""
        if not self._async_queue:
            return
        await self._bp.enqueue_event(event, self._async_queue)

    async def _initiate_shutdown(self) -> None:
        """Best-effort shutdown of queue loop.

        This method must not block indefinitely: during process shutdown or
        test teardown, worker tasks may stop consuming (e.g., global shutdown
        flag), so awaiting `queue.join()` can deadlock.
        """
        if not self._stop_event:
            return

        # Cancel workers so they promptly unwind.
        for worker in list(self._workers):
            try:
                worker.cancel()
            except Exception:
                pass

        # Drain any remaining queued items to keep internal unfinished-task
        # counters consistent (in case anyone else awaits join()).
        if self._async_queue:
            while True:
                try:
                    self._async_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                else:
                    self._async_queue.task_done()

        self._stop_event.set()


def get_aggregated_event_stream_stats() -> dict[str, int]:
    """Aggregate stats across all live EventStream instances.

    .. deprecated::
        Moved to :func:`backend.ledger.stream_stats.get_aggregated_event_stream_stats`.
        This re-export exists for backward compatibility.
    """
    from backend.ledger.stream_stats import (
        get_aggregated_event_stream_stats as _impl,
    )

    return _impl()


Ledger = EventStream


__all__ = [
    "Ledger",
    "EventStream",
    "EventStreamSubscriber",
    "get_aggregated_event_stream_stats",
]
