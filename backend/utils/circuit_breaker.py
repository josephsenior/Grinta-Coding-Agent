from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock


@dataclass
class _BreakerState:
    state: str = "closed"  # closed | open | half_open
    failures: int = 0
    opened_at: float = 0.0
    open_seconds: float = 0.0
    half_open_probes_left: int = 0


class CircuitBreaker:
    """Adaptive circuit breaker with exponential backoff and half-open probes."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.lock = asyncio.Lock()
        self.state = _BreakerState()
        # Config
        self.failure_threshold = int(os.getenv("FORGE_CB_FAILURE_THRESHOLD", "3"))
        self.base_open_seconds = float(os.getenv("FORGE_CB_BASE_OPEN_SECONDS", "2"))
        self.max_open_seconds = float(os.getenv("FORGE_CB_MAX_OPEN_SECONDS", "60"))
        self.half_open_probes = int(os.getenv("FORGE_CB_HALF_OPEN_PROBES", "1"))

    async def async_call(self, fn: Callable[[], Awaitable]):
        """Execute fn under breaker control."""
        async with self.lock:
            now = time.time()
            if self.state.state == "open":
                if now - self.state.opened_at >= self.state.open_seconds:
                    # Transition to half-open
                    self.state.state = "half_open"
                    self.state.half_open_probes_left = max(1, self.half_open_probes)
                else:
                    _CB_METRICS.on_blocked(self.key)
                    raise RuntimeError(f"circuit_open:{self.key}")

            if self.state.state == "half_open":
                if self.state.half_open_probes_left <= 0:
                    _CB_METRICS.on_blocked(self.key)
                    raise RuntimeError(f"circuit_half_open_block:{self.key}")
                self.state.half_open_probes_left -= 1
                _CB_METRICS.on_half_open_probe(self.key)

        # Execute outside lock
        try:
            result = await fn()
        except Exception:
            async with self.lock:
                self._on_failure()
            raise

        async with self.lock:
            self._on_success()
        return result

    def _on_failure(self) -> None:
        st = self.state
        st.failures += 1
        if st.state == "half_open":
            # Re-open with increased backoff
            st.state = "open"
            st.opened_at = time.time()
            st.open_seconds = min(
                self.max_open_seconds,
                max(
                    self.base_open_seconds,
                    2 * st.open_seconds or self.base_open_seconds,
                ),
            )
            _CB_METRICS.on_open(self.key)
            return
        if st.failures >= self.failure_threshold and st.state == "closed":
            st.state = "open"
            st.opened_at = time.time()
            st.open_seconds = max(
                self.base_open_seconds, st.open_seconds or self.base_open_seconds
            )
            _CB_METRICS.on_open(self.key)

    def _on_success(self) -> None:
        st = self.state
        if st.state == "half_open":
            # Close and reset
            st.state = "closed"
            st.failures = 0
            st.open_seconds = max(
                self.base_open_seconds, st.open_seconds or self.base_open_seconds
            )
            _CB_METRICS.on_close_success(self.key)
        elif st.state == "closed":
            # Healthy path; reset failures
            st.failures = 0


class CircuitBreakerManager:
    """Holds breakers by key and exposes async helper."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    @property
    def breakers(self) -> dict[str, CircuitBreaker]:
        """Get all registered circuit breakers."""
        return self._breakers

    def get(self, key: str) -> CircuitBreaker:
        with self._lock:
            br = self._breakers.get(key)
            if br is None:
                br = CircuitBreaker(key)
                self._breakers[key] = br
            return br

    async def async_call(self, key: str, fn: Callable[[], Awaitable]):
        return await self.get(key).async_call(fn)

    def snapshot(self) -> dict:
        with self._lock:
            open_keys = []
            for k, br in self._breakers.items():
                if br.state.state == "open":
                    open_keys.append(k)
            return {
                "keys": list(self._breakers.keys()),
                "open_keys": open_keys,
                "open_count": len(open_keys),
            }


class _BreakerMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._data = {
            "opens_total": 0,
            "blocked_total": 0,
            "half_open_probes_total": 0,
            "close_success_total": 0,
        }

    def on_open(self, key: str) -> None:
        with self._lock:
            self._data["opens_total"] += 1

    def on_blocked(self, key: str) -> None:
        with self._lock:
            self._data["blocked_total"] += 1

    def on_half_open_probe(self, key: str) -> None:
        with self._lock:
            self._data["half_open_probes_total"] += 1

    def on_close_success(self, key: str) -> None:
        with self._lock:
            self._data["close_success_total"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)


_CB_MANAGER = CircuitBreakerManager()
_CB_METRICS = _BreakerMetrics()


def get_circuit_breaker_manager() -> CircuitBreakerManager:
    return _CB_MANAGER


def get_circuit_breaker_metrics_snapshot() -> dict:
    snap = _CB_METRICS.snapshot()
    mgr = _CB_MANAGER.snapshot()
    snap.update(
        {
            "open_keys": mgr["open_keys"],
            "open_count": mgr["open_count"],
        }
    )
    return snap


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerManager",
    "get_circuit_breaker_manager",
    "get_circuit_breaker_metrics_snapshot",
]
