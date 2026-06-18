"""Centralized runtime manager for runtime lifecycle and warm pool tracking."""

from __future__ import annotations

import subprocess
import threading
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeServerInfo:
    """Process and networking metadata for a managed runtime instance."""

    process: subprocess.Popen | None
    execution_server_port: int | None = None
    app_ports: list[int] = field(default_factory=list)
    log_thread: threading.Thread | None = None
    log_thread_exit_event: threading.Event | None = None
    temp_workspace: str | None = None


@dataclass(slots=True)
class _ManagedServer:
    """Internal bookkeeping record for tracked runtime instances."""

    info: RuntimeServerInfo
    kind: str
    session_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Update last used timestamp."""
        self.last_used_at = time.time()


class RuntimeManager:
    """Global coordinator for runtime pooling, lifecycle, and metrics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._warm: list[_ManagedServer] = []
        self._running: dict[str, _ManagedServer] = {}

    # ------------------------------------------------------------------
    # Warm pool management
    # ------------------------------------------------------------------
    def add_warm_server(
        self, kind: str, info: RuntimeServerInfo, metadata: dict[str, str] | None = None
    ) -> None:
        """Register a warm (pre-started) runtime instance."""
        record = _ManagedServer(
            info=info,
            kind=kind,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._warm.append(record)

    def acquire_warm_server(self, kind: str) -> RuntimeServerInfo | None:
        """Acquire a warm runtime instance for immediate use."""
        with self._lock:
            for idx, record in enumerate(self._warm):
                if record.kind == kind:
                    self._warm.pop(idx)
                    record.touch()
                    return record.info
        return None

    def warm_count(self, kind: str | None = None) -> int:
        """Return number of warm instances, optionally filtered by kind."""
        with self._lock:
            if kind is None:
                return len(self._warm)
            return sum(1 for record in self._warm if record.kind == kind)

    def pop_all_warm(self, kind: str) -> list[RuntimeServerInfo]:
        """Remove and return all warm instances for a given kind."""
        with self._lock:
            remaining: list[_ManagedServer] = []
            selected: list[RuntimeServerInfo] = []
            for record in self._warm:
                if record.kind == kind:
                    selected.append(record.info)
                else:
                    remaining.append(record)
            self._warm = remaining
            return selected

    # ------------------------------------------------------------------
    # Running session tracking
    # ------------------------------------------------------------------
    def register_running(
        self,
        session_id: str,
        kind: str,
        info: RuntimeServerInfo,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Register a runtime instance that is now attached to a session."""
        record = _ManagedServer(
            info=info,
            kind=kind,
            session_id=session_id,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._running[session_id] = record

    def get_running(self, session_id: str) -> RuntimeServerInfo | None:
        """Retrieve runtime info for a running session, if present."""
        with self._lock:
            record = self._running.get(session_id)
            if record is None:
                return None
            record.touch()
            return record.info

    def deregister_running(self, session_id: str) -> RuntimeServerInfo | None:
        """Remove a running session from tracking and return its info."""
        with self._lock:
            record = self._running.pop(session_id, None)
        if record is None:
            return None
        return record.info

    def running_count(self, kind: str | None = None) -> int:
        """Return number of running instances, optionally filtered by kind."""
        with self._lock:
            if kind is None:
                return len(self._running)
            return sum(1 for record in self._running.values() if record.kind == kind)

    def list_session_ids(self, kind: str | None = None) -> list[str]:
        """List tracked session IDs."""
        with self._lock:
            if kind is None:
                return list(self._running.keys())
            return [
                session_id
                for session_id, record in self._running.items()
                if record.kind == kind
            ]

    # ------------------------------------------------------------------
    # Metrics & observability
    # ------------------------------------------------------------------
    def metrics_snapshot(self) -> dict[str, dict[str, int]]:
        """Return a snapshot of warm/running pool sizes by kind."""
        with self._lock:
            warm_counter = Counter(record.kind for record in self._warm)
            running_counter = Counter(record.kind for record in self._running.values())
        return {
            'warm': dict(warm_counter),
            'running': dict(running_counter),
        }

    def heartbeat(self, session_id: str) -> None:
        """Update last-used timestamp for a running session."""
        with self._lock:
            record = self._running.get(session_id)
            if record:
                record.touch()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def iterate_warm_infos(
        self, kind: str | None = None
    ) -> Iterable[RuntimeServerInfo]:
        """Yield warm runtime infos without mutating the pool."""
        with self._lock:
            snapshot = list(self._warm)
        for record in snapshot:
            if kind is None or record.kind == kind:
                yield record.info


# Shared singleton instance used across runtime implementations.
runtime_manager = RuntimeManager()

__all__ = [
    'RuntimeManager',
    'RuntimeServerInfo',
    'runtime_manager',
]
