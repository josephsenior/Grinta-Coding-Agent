from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass

from backend.runtime.base import Runtime


@dataclass(slots=True)
class PooledRuntime:
    runtime: Runtime
    repo_directory: str | None = None


@dataclass(slots=True)
class WarmPoolPolicy:
    """Policy describing warm pool size + TTL for a specific runtime kind."""

    max_size: int
    ttl_seconds: float


class RuntimePool:
    """Abstract runtime pool interface."""

    def acquire(self, key: str) -> PooledRuntime | None:
        raise NotImplementedError

    def release(self, key: str, runtime: PooledRuntime) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, int]:
        return {}

    def cleanup_expired(self) -> int:
        """Optional hook for proactive cleanup."""
        return 0

    def idle_reclaim_stats(self) -> dict[str, int]:
        """Optional counter export for idle runtime cleanup events."""
        return {}

    def eviction_stats(self) -> dict[str, int]:
        """Optional counter export for pool evictions when capacity is exceeded."""
        return {}


class SingleUseRuntimePool(RuntimePool):
    """Default pool that never reuses runtimes."""

    def acquire(self, key: str) -> PooledRuntime | None:
        return None

    def release(self, key: str, runtime: PooledRuntime) -> None:
        call_async_disconnect(runtime.runtime)


class WarmRuntimePool(RuntimePool):
    """Simple warm pool keyed by runtime kind."""

    def __init__(
        self, *, max_size_per_key: int = 2, ttl_seconds: float = 600.0
    ) -> None:
        default_policy = WarmPoolPolicy(
            max_size=max_size_per_key,
            ttl_seconds=ttl_seconds,
        )
        self._lock = threading.RLock()
        self._pool: dict[str, deque[tuple[float, PooledRuntime]]] = {}
        self._idle_reclaims: Counter[str] = Counter()
        self._evictions: Counter[str] = Counter()
        self._default_policy: WarmPoolPolicy = default_policy
        self._policy_overrides: dict[str, WarmPoolPolicy] = {}

    def acquire(self, key: str) -> PooledRuntime | None:
        with self._lock:
            policy = self._policy_for(key)
            if policy.max_size <= 0:
                self._pool.pop(key, None)
                return None
            queue = self._pool.get(key)
            if not queue:
                return None
            while queue:
                timestamp, pooled = queue.popleft()
                if time.time() - timestamp <= policy.ttl_seconds:
                    return pooled
                call_async_disconnect(pooled.runtime)
                self._idle_reclaims[key] += 1
            return None

    def release(self, key: str, runtime: PooledRuntime) -> None:
        policy = self._policy_for(key)
        if policy.max_size <= 0:
            call_async_disconnect(runtime.runtime)
            return
        with self._lock:
            queue = self._pool.setdefault(key, deque())
            queue.append((time.time(), runtime))
            while len(queue) > policy.max_size:
                _, evicted = queue.popleft()
                call_async_disconnect(evicted.runtime)
                self._evictions[key] += 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {key: len(queue) for key, queue in self._pool.items()}

    def cleanup_expired(self) -> int:
        """Remove runtimes whose TTL has elapsed without waiting for re-acquire."""
        removed = 0
        now = time.time()
        with self._lock:
            for key, queue in list(self._pool.items()):
                policy = self._policy_for(key)
                refreshed: deque[tuple[float, PooledRuntime]] = deque()
                while queue:
                    timestamp, pooled = queue.popleft()
                    if now - timestamp > policy.ttl_seconds:
                        removed += 1
                        call_async_disconnect(pooled.runtime)
                        self._idle_reclaims[key] += 1
                    else:
                        refreshed.append((timestamp, pooled))
                self._pool[key] = refreshed
        return removed

    def remove_runtime(self, key: str, runtime: Runtime) -> bool:
        """Remove a specific runtime instance from the pool if present."""
        with self._lock:
            queue = self._pool.get(key)
            if not queue:
                return False
            removed = False
            refreshed: deque[tuple[float, PooledRuntime]] = deque()
            while queue:
                timestamp, pooled = queue.popleft()
                if pooled.runtime is runtime:
                    removed = True
                    call_async_disconnect(runtime)
                else:
                    refreshed.append((timestamp, pooled))
            self._pool[key] = refreshed
            return removed

    def idle_reclaim_stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._idle_reclaims)

    def eviction_stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._evictions)

    def configure_policies(
        self,
        default_policy: WarmPoolPolicy,
        overrides: dict[str, WarmPoolPolicy],
    ) -> None:
        with self._lock:
            self._default_policy = default_policy
            self._policy_overrides = dict(overrides)
            self._enforce_policy_limits_locked()

    def _policy_for(self, key: str) -> WarmPoolPolicy:
        return self._policy_overrides.get(key, self._default_policy)

    def _enforce_policy_limits_locked(self) -> None:
        for key, queue in list(self._pool.items()):
            policy = self._policy_for(key)
            if policy.max_size <= 0:
                while queue:
                    _, pooled = queue.popleft()
                    call_async_disconnect(pooled.runtime)
                    self._evictions[key] += 1
                self._pool.pop(key, None)
                continue
            while len(queue) > policy.max_size:
                _, evicted = queue.popleft()
                call_async_disconnect(evicted.runtime)
                self._evictions[key] += 1


def call_async_disconnect(runtime: Runtime) -> None:
    from backend.core.logger import FORGE_logger as logger

    disconnect_fn = getattr(runtime, "disconnect", None)
    try:
        if callable(disconnect_fn):
            from backend.core.constants import GENERAL_TIMEOUT
            from backend.utils.async_utils import call_async_from_sync

            call_async_from_sync(disconnect_fn, GENERAL_TIMEOUT)
        else:
            runtime.close()
    except Exception as exc:
        logger.warning("Error disconnecting runtime %s: %s", runtime.sid, exc)
