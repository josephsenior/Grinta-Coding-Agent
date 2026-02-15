from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger
from backend.runtime.pool import call_async_disconnect
from backend.runtime.telemetry import RuntimeTelemetry, runtime_telemetry

if TYPE_CHECKING:
    from backend.events.stream import EventStream
    from backend.runtime.base import Runtime
    from backend.runtime.pool import RuntimePool


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class WatchedRuntime:
    runtime: Runtime
    key: str
    session_id: str | None
    acquired_at: float
    last_activity: float
    event_stream: EventStream | None
    listener_handle: str | None


class RuntimeWatchdog:
    """Background watchdog that enforces runtime lifecycle guarantees."""

    def __init__(
        self,
        *,
        max_active_seconds: float | None = None,
        poll_interval: float | None = None,
        telemetry: RuntimeTelemetry | None = None,
    ) -> None:
        self._max_active_seconds = (
            max_active_seconds
            if max_active_seconds is not None
            else _env_float("FORGE_RUNTIME_MAX_ACTIVE_SECONDS", 3600.0)
        )
        self._poll_interval = (
            poll_interval
            if poll_interval is not None
            else _env_float("FORGE_RUNTIME_WATCHDOG_INTERVAL", 30.0)
        )
        self._telemetry = telemetry or runtime_telemetry
        self._watched: dict[str, WatchedRuntime] = {}
        self._lock = threading.RLock()
        self._cleanup_hook: Callable[[], int] | None = None
        self._stop_event = threading.Event()
        self._tick = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="RuntimeWatchdog", daemon=True
        )
        self._tick.set()
        self._thread.start()

    def configure(
        self,
        *,
        max_active_seconds: float | None = None,
        poll_interval: float | None = None,
    ) -> None:
        if max_active_seconds is not None:
            self._max_active_seconds = max_active_seconds
        if poll_interval is not None:
            self._poll_interval = poll_interval
        self._tick.set()

    def set_idle_cleanup(self, pool: RuntimePool | None) -> None:
        cleanup = getattr(pool, "cleanup_expired", None) if pool else None
        if callable(cleanup):
            self._cleanup_hook = cleanup
        else:
            self._cleanup_hook = None

    def watch_runtime(
        self,
        runtime: Runtime,
        *,
        key: str,
        session_id: str | None,
    ) -> None:
        if self._max_active_seconds <= 0:
            return
        event_stream = getattr(runtime, "event_stream", None)
        if event_stream is None:
            return
        sid = runtime.sid
        now = time.time()
        with self._lock:
            existing = self._watched.get(sid)
            if existing:
                existing.key = key
                existing.session_id = session_id
                existing.runtime = runtime
                existing.acquired_at = now
                existing.last_activity = now
                return

            def _on_activity(_sid: str = sid) -> None:
                self.heartbeat(_sid)

            handle = event_stream.add_activity_listener(_on_activity)
            self._watched[sid] = WatchedRuntime(
                runtime=runtime,
                key=key,
                session_id=session_id,
                acquired_at=now,
                last_activity=now,
                event_stream=event_stream,
                listener_handle=handle,
            )
        self._tick.set()

    def unwatch_runtime(self, runtime: Runtime) -> None:
        sid = runtime.sid
        with self._lock:
            meta = self._watched.pop(sid, None)
        if meta:
            self._detach_listener(meta)
        self._tick.set()

    def heartbeat(self, sid: str) -> None:
        if self._max_active_seconds <= 0:
            return
        with self._lock:
            meta = self._watched.get(sid)
            if meta:
                meta.last_activity = time.time()

    def reset_for_tests(self) -> None:  # pragma: no cover - helper for test cleanup
        with self._lock:
            metas = list(self._watched.values())
            self._watched.clear()
        for meta in metas:
            self._detach_listener(meta)
        self._tick.set()

    def stop(self) -> None:  # pragma: no cover - graceful shutdown helper
        self._stop_event.set()
        self._tick.set()
        self._thread.join(timeout=5)

    def stats(self) -> dict[str, int]:
        """Return a snapshot of currently watched runtimes keyed by runtime kind."""
        with self._lock:
            counts: dict[str, int] = {}
            for meta in self._watched.values():
                counts[meta.key] = counts.get(meta.key, 0) + 1
        return counts

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._tick.wait(self._poll_interval)
            self._tick.clear()
            if self._stop_event.is_set():
                break
            self._enforce_deadlines()
            if self._cleanup_hook:
                try:
                    removed = self._cleanup_hook()
                    if removed:
                        logger.debug(
                            "Runtime pool cleanup removed %s runtimes", removed
                        )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("Runtime pool cleanup failed: %s", exc)

    def _enforce_deadlines(self) -> None:
        if self._max_active_seconds <= 0:
            return
        now = time.time()
        overdue: list[WatchedRuntime] = []
        with self._lock:
            for meta in list(self._watched.values()):
                if now - meta.last_activity > self._max_active_seconds:
                    overdue.append(meta)
                    self._watched.pop(meta.runtime.sid, None)
        for meta in overdue:
            self._detach_listener(meta)
            self._terminate(meta, reason="active_timeout")

    def _terminate(self, meta: WatchedRuntime, *, reason: str) -> None:
        logger.warning(
            "Runtime watchdog terminating runtime sid=%s key=%s reason=%s",
            meta.runtime.sid,
            meta.key,
            reason,
        )
        try:
            call_async_disconnect(meta.runtime)
        finally:
            self._telemetry.record_watchdog_termination(meta.key, reason)

    def _detach_listener(self, meta: WatchedRuntime) -> None:
        if meta.event_stream and meta.listener_handle:
            try:
                meta.event_stream.remove_activity_listener(meta.listener_handle)
            except Exception:  # pragma: no cover - defensive
                pass


runtime_watchdog = RuntimeWatchdog()
