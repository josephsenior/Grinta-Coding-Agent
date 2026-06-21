"""Event stream implementation with pub/sub and persistence helpers.

Backpressure is delegated to :mod:`backend.ledger.stream.backpressure` and durable
persistence / WAL recovery to :mod:`backend.ledger.stream.persistence`.
"""

# mypy: disable-error-code="unreachable"

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import threading
import time
import uuid
import weakref
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from backend.core.logging.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.core.workspace_resolution import workspace_agent_state_dir
from backend.ledger.event import Event, EventSource
from backend.ledger.event.event_store import EventStore
from backend.ledger.infra.config import get_event_runtime_defaults
from backend.ledger.infra.secret_masker import SecretMasker
from backend.ledger.serialization.event import event_from_dict, event_to_dict
from backend.ledger.stream.backpressure import BackpressureManager
from backend.ledger.stream.coalescing import EventCoalescer
from backend.ledger.stream.persistence import EventPersistence
from backend.persistence.locations import get_conversation_dir
from backend.utils.async_helpers.async_utils import (
    call_sync_from_async,
    get_main_event_loop,
    run_or_schedule,
)

if TYPE_CHECKING:
    from backend.persistence import FileStore


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
    """weakref.finalize callback -- fires if a stream is GC'd without close()."""
    import sys

    # During interpreter/test shutdown, logging handlers and IO streams may
    # already be torn down.  The logging module prints noisy
    # ``--- Logging error --- / ValueError: I/O operation on closed file``
    # tracebacks internally *before* raising, so a try/except cannot silence
    # them.  Bypass the logging subsystem entirely and write to stderr
    # directly -- if it is still usable.
    if sys.is_finalizing():
        return
    stderr = getattr(sys, 'stderr', None)
    if stderr is None or getattr(stderr, 'closed', True):
        return
    try:
        stderr.write(
            f"WARNING: EventStream '{sid}' was GC'd without close(); "
            'resources may leak.\n'
        )
    except (ValueError, OSError):
        pass


def _invoke_pre_dispatch_hook(hook: Callable[[Any], None], event: Event) -> None:
    """Invoke a pre-dispatch hook after local type narrowing."""
    hook(event)


def _acquire_session_lock(lock_path: str, lock_data: str) -> Any:
    """Acquire an OS-level exclusive session lock or raise immediately."""
    if not OS_CAPS.is_windows:
        import fcntl  # type: ignore[import-not-found]

        handle = open(lock_path, 'w', encoding='utf-8')
        try:
            fcntl.flock(  # type: ignore[attr-defined]
                handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB  # type: ignore[attr-defined]
            )
            handle.write(lock_data)
            handle.flush()
            os.fsync(handle.fileno())
            return handle
        except Exception:
            with contextlib.suppress(Exception):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
            handle.close()
            raise

    import msvcrt

    handle = open(lock_path, 'w+b')  # type: ignore[assignment]
    try:
        handle.write(lock_data.encode('utf-8'))
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return handle
    except Exception:
        with contextlib.suppress(Exception):
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()
        raise


class EventStream(EventStore):
    """Thread-safe event stream with pub/sub functionality.

    Extends EventStore with subscriber management and async event delivery.
    Events are queued and dispatched to subscribers in background threads
    with dedicated event loops for each callback.

    Heavy-lifting is delegated to composable helpers:

    * :class:`BackpressureManager` -- queue sizing, stats, rate windows.
    * :class:`EventPersistence` -- WAL, file writes, cache pages, SQLite.
    """

    secrets: dict[str, str]
    _subscribers: dict[str, dict[str, Callable]]
    _lock: threading.Lock
    _async_queue: asyncio.Queue[Event] | None
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

        self._session_lock_path: str | None = None
        self._session_lock_handle: Any = None
        try:
            lock_dir = os.fspath(workspace_agent_state_dir() / 'locks')
            os.makedirs(lock_dir, exist_ok=True)
            self._session_lock_path = os.path.join(lock_dir, f'{sid}.lock')
            current_pid = os.getpid()
            current_time = time.time()
            session_marker = uuid.uuid4().hex[:16]
            lock_data = (
                f'pid={current_pid};started={current_time:.0f};'
                f'marker={session_marker};host={os.environ.get("COMPUTERNAME", "unknown")}'
            )
            self._session_lock_handle = _acquire_session_lock(
                self._session_lock_path,
                lock_data,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not acquire exclusive session lock for '{sid}'. "
                'Another Grinta process may already be using this session.'
            ) from exc
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
            '1',
            'true',
            'yes',
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
            existing_sqlite_store=getattr(self, '_sqlite_store', None),
        )
        self._persistence_health: Literal['ok', 'degraded', 'failed'] = 'ok'
        self._persist_failure_streak: int = 0
        self._persist_failure_threshold: int = 3

        # ---- Queue / threading setup --------------------------------------
        # inline_delivery=True: all events are delivered synchronously in the
        # same call chain as add_event(), like USER events always are.
        # This eliminates the thread-pool race that causes action ID mismatches
        # in single-session CLI use. Set automatically when worker_count=0.
        _wc = int(worker_count if worker_count is not None else event_defaults.workers)
        self._inline_delivery: bool = _wc == 0
        self._queue_loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[Event | object] | None = None
        self._queue_ready = threading.Event()
        self._worker_count = max(1, _wc) if not self._inline_delivery else 1
        self._delivery_pool = ThreadPoolExecutor(max_workers=self._worker_count)
        self._workers: list[asyncio.Task[Any]] = []
        self._stop_event: asyncio.Event | None = None
        self._stop_sentinel = object()
        if not self._inline_delivery:
            self._queue_thread = threading.Thread(
                target=self._run_queue_loop, daemon=True
            )
            self._queue_thread.start()
        else:
            # In inline mode the queue thread is not used; mark ready immediately.
            self._queue_ready.set()

        # ---- Subscribers / secrets -----------------------------------------
        self._subscribers = {}
        self._lock = threading.Lock()
        self._secret_masker = SecretMasker()
        self.secrets = self._secret_masker.secrets
        self._activity_listeners: dict[str, Callable[[str], None]] = {}
        self._activity_listener_lock = threading.RLock()
        self._activity_listener_seq = 0
        self._write_page_cache: list[dict] = []

        # If set, called for runnable Actions after id assignment and persistence
        # but *before* subscriber delivery. Required so pending-action state is
        # registered before synchronous (inline) runtime handlers can emit
        # observations (otherwise cause-based routing sees no outstanding row).
        self.pre_runnable_action_dispatch: Callable[[Any], None] | None = None
        self._pre_dispatch_lock: asyncio.Lock | None = None
        self._pre_dispatch_lock_loop: asyncio.AbstractEventLoop | None = None

        # Register for global metrics aggregation
        try:  # pragma: no cover - defensive
            EventStream._GLOBAL_STREAMS.add(self)
        except Exception:
            logger.warning(
                'Failed to register EventStream for global metrics', exc_info=True
            )

        # Safety finalizer -- ensures close() is called if the stream is GC'd
        # without an explicit close().  weakref.finalize is safe: it won't
        # prevent GC and fires exactly once.
        self._finalizer = weakref.finalize(self, _warn_unclosed_stream, self.sid)

        # Replay any incomplete writes from a previous crash
        recovered_count = self._persist.replay_pending_events()

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
        # If WAL replay recovered events, recalculate cur_id atomically
        # while holding the lock to prevent race conditions with concurrent
        # add_event() calls.
        if recovered_count > 0:
            with self._lock:
                self._cur_id = self._calculate_cur_id()
                logger.debug(
                    'WAL replay: recalculated cur_id=%d after recovering %d events',
                    self._cur_id,
                    recovered_count,
                )

    def _shutdown_async_queue(self) -> None:
        if self._inline_delivery:
            self._delivery_pool.shutdown(wait=False)
            return
        if self._queue_loop and self._stop_event:
            future = asyncio.run_coroutine_threadsafe(
                self._initiate_shutdown(), self._queue_loop
            )
            try:
                future.result(timeout=5)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug('Error shutting down event queue: %s', exc)
        if self._queue_thread.is_alive():
            # Never block forever during teardown; the thread is daemonized.
            self._queue_thread.join(timeout=5)
            if self._queue_thread.is_alive():
                logger.debug(
                    "EventStream '%s' queue thread did not stop within timeout; continuing",
                    self.sid,
                )

    def pre_dispatch_lock(self) -> asyncio.Lock:
        """Return a loop-bound lock serializing one-shot pre-dispatch hook swaps."""
        loop = asyncio.get_running_loop()
        if self._pre_dispatch_lock is None or self._pre_dispatch_lock_loop is not loop:
            self._pre_dispatch_lock = asyncio.Lock()
            self._pre_dispatch_lock_loop = loop
        return self._pre_dispatch_lock

    def _close_persist_and_super(self) -> None:
        try:
            self._persist.close()
        except Exception as exc:  # pragma: no cover - defensive: already-closed path
            logger.debug('EventPersistence close raised during teardown: %s', exc)
        try:
            super().close()
        except Exception as exc:  # pragma: no cover - defensive: already-closed path
            logger.debug('EventStore close raised during teardown: %s', exc)

    def close(self) -> None:
        """Close event stream, stopping queue processing and cleaning up subscribers.

        Idempotent: safe to call multiple times (e.g. explicit close + finalizer).
        """
        with self._lock:
            if getattr(self, '_closed', False):
                return
        if self._coalescer is not None:
            for flushed in self._coalescer.flush_all():
                self._dispatch_coalesced_flushed(flushed)
        with self._lock:
            if getattr(self, '_closed', False):
                return
            self._closed = True
        if hasattr(self, '_finalizer'):
            self._finalizer.detach()
        self._stop_flag.set()
        self._flush_write_page_cache()
        self._shutdown_async_queue()
        with self._lock:
            self._subscribers.clear()
            self._activity_listeners.clear()
        if self._session_lock_handle is not None:
            try:
                if not OS_CAPS.is_windows:
                    import fcntl  # type: ignore[import-not-found]

                    fcntl.flock(  # type: ignore[attr-defined]
                        self._session_lock_handle.fileno(), fcntl.LOCK_UN  # type: ignore[attr-defined]
                    )
                else:
                    import msvcrt

                    try:
                        self._session_lock_handle.seek(0)
                        msvcrt.locking(
                            self._session_lock_handle.fileno(), msvcrt.LK_UNLCK, 1
                        )
                    except OSError:
                        pass
                self._session_lock_handle.close()
            except Exception:
                pass
            self._session_lock_handle = None
        if self._session_lock_path:
            try:
                os.unlink(self._session_lock_path)
            except OSError:
                pass
        self._close_persist_and_super()

    def get_backpressure_snapshot(self) -> dict[str, int]:
        """Return a lightweight snapshot of enqueue/drop stats.

        Intended for health classification in long-running sessions.
        """
        snapshot = self._bp.get_snapshot(self._started_at_monotonic)
        # Merge persistence stats
        snapshot.update(self._persist.stats)
        snapshot.update(self._persist.get_health_snapshot())
        snapshot['persist_failures_window_count'] = int(
            len(self._persist._recent_persist_failures)
        )
        now = time.monotonic()
        window = self._persist._persist_failure_window_seconds
        recent_failures = [
            ts for ts in self._persist._recent_persist_failures if now - ts < window
        ]
        snapshot['persist_failures_per_minute'] = (
            int(round(len(recent_failures) * 60 / max(window, 1))) if window > 0 else 0
        )
        dw = self._persist.durable_writer
        if dw:
            snapshot['durable_writer_drops'] = int(dw.drop_count)
            snapshot['durable_writer_queue_depth'] = int(dw.queue_depth)
            snapshot['durable_writer_errors'] = int(dw.error_count)
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
            logger.debug('iter_global_streams failed: %s', exc)
            return []

    def _clean_up_subscriber(self, subscriber_id: str, callback_id: str) -> None:
        """Clean up a specific subscriber callback."""
        if subscriber_id not in self._subscribers:
            logger.warning('Subscriber not found during cleanup: %s', subscriber_id)
            return
        if callback_id not in self._subscribers[subscriber_id]:
            logger.warning('Callback not found during cleanup: %s', callback_id)
            return

        del self._subscribers[subscriber_id][callback_id]
        if not self._subscribers[subscriber_id]:
            del self._subscribers[subscriber_id]

    def subscribe(
        self,
        subscriber_id: str,
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
        with self._lock:
            if subscriber_id not in self._subscribers:
                self._subscribers[subscriber_id] = {}
            if callback_id in self._subscribers[subscriber_id]:
                msg = f'Callback ID on subscriber {subscriber_id} already exists: {callback_id}'
                raise ValueError(msg)
            self._subscribers[subscriber_id][callback_id] = callback

    def unsubscribe(self, subscriber_id: str, callback_id: str) -> None:
        """Unsubscribe callback from event stream and clean up resources.

        Args:
            subscriber_id: Subscriber identifier
            callback_id: Callback identifier to remove

        """
        with self._lock:
            if subscriber_id not in self._subscribers:
                logger.debug(
                    'Subscriber not found during unsubscribe: %s', subscriber_id
                )
                return
            if callback_id not in self._subscribers[subscriber_id]:
                logger.debug('Callback not found during unsubscribe: %s', callback_id)
                return
            self._clean_up_subscriber(subscriber_id, callback_id)

    def _maybe_merge_coalesced_event(self, event: Event) -> Event | None:
        """Return event to process, or None if caller should return early."""
        if not self._coalescer or not self._coalescer.should_coalesce(event):
            return event
        merged = self._coalescer.absorb(event)
        if merged is None:
            return None
        return merged

    def _run_pre_dispatch_hook_if_runnable(self, sanitized_event: Event) -> None:
        hook = self.pre_runnable_action_dispatch
        if not (callable(hook) and getattr(sanitized_event, 'runnable', False)):
            return
        try:
            _invoke_pre_dispatch_hook(hook, sanitized_event)
        except Exception as exc:  # pragma: no cover - hook must not break delivery
            logger.error(
                'pre_runnable_action_dispatch failed: %s',
                exc,
                exc_info=True,
            )

    def add_event(self, event: Event, source: EventSource) -> None:
        """Add event to stream with automatic ID assignment and persistence."""
        if self._should_drop_due_to_shutdown(event, source):
            return

        # Optional event coalescing for high-frequency event types
        resolved = self._maybe_merge_coalesced_event(event)
        if resolved is None:
            return
        event = resolved

        if self._coalescer:
            for flushed in self._coalescer.flush_expired():
                self._dispatch_coalesced_flushed(flushed)

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
        #
        # Persistence failure is intentionally non-fatal: a transient I/O
        # error (disk full, SQLite lock, AV scan) must not prevent the event
        # from being delivered to subscribers.  Durability is degraded for
        # that event, but the session continues.  A dead session caused by a
        # recoverable disk blip violates the runtime stability contract.
        if sanitized_event.id is not None:
            try:
                self._persist.persist_event(payload, sanitized_event.id, cache_payload)
                self._record_persist_success()
            except Exception:
                self._record_persist_failure(sanitized_event.id)
                logger.error(
                    'EventStream: persist_event failed for event id=%s; '
                    'continuing with in-memory delivery (durability degraded, '
                    'persistence_health=%s)',
                    sanitized_event.id,
                    self._persistence_health,
                    exc_info=True,
                )

        # Arm pending with *sanitized_event*, the same object the stream delivers
        # to subscribers (runtime, controller). A round-trip can diverge from the
        # original in-place ``event``; ``observation.cause`` is keyed to the
        # delivered action's id, so the pending map must use that id.
        self._run_pre_dispatch_hook_if_runnable(sanitized_event)

        if source == EventSource.USER or self._inline_delivery:
            self._dispatch_event_inline(sanitized_event)
        else:
            self._enqueue_serialized_event(sanitized_event)
        self._notify_activity_listeners()

    @property
    def persistence_health(self) -> Literal['ok', 'degraded', 'failed']:
        """Durability health based on recent persist_event outcomes."""
        return self._persistence_health

    def _record_persist_success(self) -> None:
        if self._persist_failure_streak > 0:
            logger.info(
                'EventStream persistence recovered after %d failure(s)',
                self._persist_failure_streak,
                extra={'msg_type': 'PERSISTENCE_RECOVERED'},
            )
        self._persist_failure_streak = 0
        self._persistence_health = 'ok'

    def _record_persist_failure(self, event_id: object) -> None:
        self._persist_failure_streak += 1
        if self._persist_failure_streak >= self._persist_failure_threshold:
            self._persistence_health = 'failed'
        elif self._persistence_health == 'ok':
            self._persistence_health = 'degraded'
        logger.warning(
            'EventStream persistence failure streak=%d health=%s event_id=%s',
            self._persist_failure_streak,
            self._persistence_health,
            event_id,
            extra={
                'msg_type': 'PERSISTENCE_DEGRADED',
                'persistence_health': self._persistence_health,
                'persist_failure_streak': self._persist_failure_streak,
            },
        )

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
        if getattr(self, '_closed', False):
            return
        for subscriber_id, callback_id, callback in callbacks:
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    run_or_schedule(result)  # type: ignore[unreachable]
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error(
                    'Error in inline event callback %s for subscriber %s: %s',
                    callback_id,
                    subscriber_id,
                    exc,
                )

    def _should_drop_due_to_shutdown(self, event: Event, source: EventSource) -> bool:
        if not self._stop_flag.is_set():
            return False
        logger.debug(
            'EventStream closed; dropping event id=%s from source=%s',
            getattr(event, 'id', None),
            source,
        )
        return True

    def _ensure_event_can_be_added(self, event: Event) -> None:
        evt_id = getattr(event, 'id', Event.INVALID_ID)
        if not isinstance(evt_id, int):
            evt_id = Event.INVALID_ID
        if evt_id != Event.INVALID_ID:
            msg = (
                f'Event already has an ID:{evt_id}. It was probably added back to the '
                'EventStream from inside a handler, triggering a loop.'
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
            next_event_id = self._cur_id
            if next_event_id is None:
                next_event_id = self._calculate_cur_id()
                # Guard: _calculate_cur_id() must return a non-negative integer.
                # A negative value means both SQLite and file-based ID scans
                # returned no useful data -- likely a storage failure.  Raising
                # here is safer than silently assigning ID 0 and risk colliding
                # with events that may have persisted but aren't visible right now.
                if not isinstance(next_event_id, int) or next_event_id < 0:
                    raise RuntimeError(
                        f'EventStream({self.sid}): _calculate_cur_id() returned '
                        f'{next_event_id!r} -- cannot assign a safe event ID. '
                        'Check storage health (SQLite integrity, filesystem access).'
                    )
            event.id = next_event_id
            event.sequence = next_event_id
            self._cur_id = next_event_id + 1

        data = self._replace_secrets(event_to_dict(event))
        sanitized_event = event_from_dict(data)

        if isinstance(sanitized_event, ChangeAgentStateAction):
            logger.debug(
                'Queued ChangeAgentStateAction id=%s state=%s source=%s',
                sanitized_event.id,
                getattr(sanitized_event, 'agent_state', None),
                sanitized_event.source,
            )

        with self._lock:
            cache_entry = self._serialize_for_cache(data)
            current_write_page = self._write_page_cache
            current_write_page.append(cache_entry)
            if len(current_write_page) == self.cache_size:
                cache_page_data = current_write_page
                self._write_page_cache = []

        return sanitized_event, data, cache_page_data

    def _flush_write_page_cache(self) -> None:
        """Flush any partial write-page cache entries to persistence.

        Called during close() to persist partial cache pages for read
        performance. Events are already individually durably persisted;
        this only improves batch read performance on session restore.
        """
        with self._lock:
            if not self._write_page_cache:
                return
            page_data = self._write_page_cache
            self._write_page_cache = []
        if not page_data:
            return
        serialized = [self._serialize_for_cache(e) for e in page_data]
        cache_payload = self._persist.build_cache_payload(serialized)
        if cache_payload is None and len(serialized) > 0:
            start_id = serialized[0].get('id', 0)
            cache_filename = self._persist._get_filename_for_cache(
                start_id, start_id + len(serialized)
            )
            cache_payload = (cache_filename, json.dumps(serialized))
        if cache_payload:
            try:
                self._persist.file_store.write(cache_payload[0], cache_payload[1])
            except Exception:
                logger.debug(
                    'Failed to flush partial write page cache on close', exc_info=True
                )

    def _dispatch_coalesced_flushed(self, event: Event) -> None:
        """Persist and dispatch a coalescer-flushed event through normal flow."""
        coalescer = self._coalescer
        self._coalescer = None
        try:
            self.add_event(event, EventSource.ENVIRONMENT)
        finally:
            self._coalescer = coalescer

    def _enqueue_serialized_event(self, event: Event) -> None:
        if not self._queue_ready.wait(timeout=2):
            logger.warning(
                'EventStream queue not ready; inline-fallback delivery for event id=%s',
                event.id,
            )
            self._dispatch_event_inline(event)
            return

        if not self._queue_loop or not self._async_queue:
            logger.warning(
                'EventStream queue loop missing; inline-fallback delivery for event id=%s',
                event.id,
            )
            self._dispatch_event_inline(event)
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._enqueue_event(event), self._queue_loop
            )
            future.result(timeout=5.0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                'Failed to enqueue event id=%s: %s; inline-fallback delivery',
                event.id,
                exc,
            )
            self._dispatch_event_inline(event)

    def add_activity_listener(self, callback: Callable[[str], None]) -> str:
        """Register a callback invoked whenever a new event is added."""
        with self._activity_listener_lock:
            handle = f'listener-{self._activity_listener_seq}'
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
                logger.debug('Activity listener raised: %s', exc)

    def set_secrets(self, secrets: dict[str, str]) -> None:
        """Set secrets dictionary for masking sensitive values in events."""
        self._secret_masker.set_secrets(secrets)
        self.secrets = self._secret_masker.secrets

    def update_secrets(self, secrets: dict[str, str]) -> None:
        """Update secrets dictionary with additional values."""
        self._secret_masker.update_secrets(secrets)
        self.secrets = self._secret_masker.secrets

    def _serialize_for_cache(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a JSON-safe deep copy of event data for cache page serialization.

        Recursively traverses all nested dicts/lists and converts non-serializable
        types (datetime, objects with .get(), etc.) to JSON-safe equivalents.
        """
        import datetime as _dt

        def _convert(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_convert(i) for i in obj]
            elif isinstance(obj, _dt.datetime):
                return obj.isoformat()
            elif isinstance(obj, _dt.date):
                return obj.isoformat()
            elif isinstance(obj, (int, float, bool, str, type(None))):
                return obj
            elif hasattr(obj, 'get') and callable(obj.get):
                try:
                    return obj.get()
                except Exception:
                    pass
            return obj

        return _convert(data)

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
                logger.error('Error retrieving event from queue: %s', e)
                continue
            if event is self._stop_sentinel:
                queue.task_done()
                break
            try:
                if not self._stop_flag.is_set():
                    await self._dispatch_event(event)
            except asyncio.CancelledError:
                self._bp.queue_size = queue.qsize()
                raise
            except Exception as e:
                logger.error('Error dispatching event: %s', e)
            finally:
                queue.task_done()
                self._bp.queue_size = queue.qsize()

    async def _dispatch_event(self, event: Event) -> None:
        """Dispatch a single event to all registered subscribers.

        Ensures ordering: all async callbacks scheduled by this event
        complete before the next event is dispatched.  Without this,
        concurrent delivery of events N and N+1 can cause subscriber
        callbacks to execute out of order on the main loop.
        """
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
            results = await asyncio.gather(*tasks, return_exceptions=True)
            cross_loop_futures = [
                r for r in results if isinstance(r, asyncio.Future) and not r.done()
            ]
            if cross_loop_futures:
                await asyncio.gather(*cross_loop_futures, return_exceptions=True)

    def _execute_callback(
        self,
        callback: Callable[[Event], Any],
        event: Event,
        subscriber_id: str,
        callback_id: str,
    ) -> Any:
        """Execute subscriber callback inside thread pool with error handling.

        If the subscriber returns an awaitable, it is scheduled on the
        application's main event loop via ``run_coroutine_threadsafe``.
        The returned ``asyncio.Future`` is passed back to ``_dispatch_event``
        so it can await completion before dispatching the next event,
        preserving per-subscriber event ordering.

        Spinning up a fresh per-event loop with ``asyncio.run`` would orphan
        any cross-loop primitives the subscriber awaits (Locks/Events/Queues
        bound to the main loop).
        """
        try:
            result = callback(event)
            if not inspect.isawaitable(result):
                return None
            main = get_main_event_loop()
            if main is not None and main.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._await_result_with_logging(result, callback_id, subscriber_id),  # type: ignore[arg-type]
                    main,
                )
                future.add_done_callback(
                    lambda f: self._handle_callback_future_done(
                        f, callback_id, subscriber_id
                    )
                )
                return future
            else:
                logger.warning(
                    'No main event loop available for callback %s; '
                    'using fallback execution (cross-loop primitives may be orphaned)',
                    callback_id,
                )
                try:
                    loop = asyncio.get_event_loop()
                    if not loop.is_closed():
                        future = asyncio.run_coroutine_threadsafe(
                            self._await_result_with_logging(
                                result, callback_id, subscriber_id
                            ),
                            loop,  # type: ignore[arg-type]
                        )
                        future.add_done_callback(
                            lambda f: self._handle_callback_future_done(
                                f, callback_id, subscriber_id
                            )
                        )
                        return future
                except RuntimeError:
                    pass
                asyncio.run(
                    self._await_result_with_logging(result, callback_id, subscriber_id)
                )  # type: ignore[arg-type]
                return None
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                'Error in event callback %s for subscriber %s: %s',
                callback_id,
                subscriber_id,
                exc,
            )
            return None

    async def _await_result_with_logging(
        self, awaitable: Any, callback_id: str, subscriber_id: str
    ) -> None:
        """Await a coroutine with error logging."""
        try:
            await awaitable
        except Exception as exc:
            logger.error(
                'Async callback %s for subscriber %s raised: %s',
                callback_id,
                subscriber_id,
                exc,
                exc_info=True,
            )

    def _handle_callback_future_done(
        self, future: Any, callback_id: str, subscriber_id: str
    ) -> None:
        """Handle completion of a callback future scheduled on the main loop."""
        try:
            exc = future.exception()
            if exc is not None:
                logger.error(
                    'Async callback %s for subscriber %s failed: %s',
                    callback_id,
                    subscriber_id,
                    exc,
                )
        except asyncio.CancelledError:
            logger.warning(
                'Async callback %s for subscriber %s was cancelled',
                callback_id,
                subscriber_id,
            )
        except Exception as exc:
            logger.error(
                'Error checking callback %s for subscriber %s: %s',
                callback_id,
                subscriber_id,
                exc,
            )

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

        # Best-effort delivery of remaining queued events with a short timeout.
        # This prevents event loss during clean shutdown while avoiding deadlock
        # if subscribers are stalled.
        if self._async_queue:
            deliver_deadline = asyncio.get_event_loop().time() + 2.0
            while True:
                try:
                    event = self._async_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                else:
                    # Attempt delivery with remaining budget.
                    remaining = deliver_deadline - asyncio.get_event_loop().time()
                    if remaining > 0 and event is not self._stop_sentinel:
                        try:
                            if isinstance(event, Event):
                                await asyncio.wait_for(
                                    self._dispatch_event(event),
                                    timeout=remaining,
                                )
                        except (asyncio.TimeoutError, Exception):
                            pass
                    self._async_queue.task_done()

        self._stop_event.set()
