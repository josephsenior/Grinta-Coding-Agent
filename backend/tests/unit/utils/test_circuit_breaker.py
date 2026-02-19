"""Unit tests for backend.utils.circuit_breaker."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerManager,
    _BreakerMetrics,
    _BreakerState,
    get_circuit_breaker_metrics_snapshot,
)


# ---------------------------------------------------------------------------
# _BreakerState
# ---------------------------------------------------------------------------


class TestBreakerState:
    def test_default_state_is_closed(self):
        s = _BreakerState()
        assert s.state == "closed"
        assert s.failures == 0
        assert s.opened_at == 0.0
        assert s.open_seconds == 0.0
        assert s.half_open_probes_left == 0

    def test_state_fields_are_mutable(self):
        s = _BreakerState()
        s.state = "open"
        s.failures = 5
        assert s.state == "open"
        assert s.failures == 5


# ---------------------------------------------------------------------------
# CircuitBreaker — state transitions
# ---------------------------------------------------------------------------


class TestCircuitBreakerTransitions:
    """Verify closed → open → half_open → closed lifecycle."""

    def _make_breaker(
        self, threshold: int = 3, base_seconds: float = 0.01
    ) -> CircuitBreaker:
        """Create a breaker with predictable config."""
        with patch.dict(
            "os.environ",
            {
                "FORGE_CB_FAILURE_THRESHOLD": str(threshold),
                "FORGE_CB_BASE_OPEN_SECONDS": str(base_seconds),
                "FORGE_CB_MAX_OPEN_SECONDS": "10",
                "FORGE_CB_HALF_OPEN_PROBES": "1",
            },
        ):
            return CircuitBreaker("test")

    async def test_closed_success_resets_failures(self):
        cb = self._make_breaker()

        async def _ok():
            return "ok"

        result = await cb.async_call(_ok)
        assert result == "ok"
        assert cb.state.failures == 0
        assert cb.state.state == "closed"

    async def test_failures_below_threshold_stay_closed(self):
        cb = self._make_breaker(threshold=3)

        async def _fail():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.async_call(_fail)

        assert cb.state.state == "closed"
        assert cb.state.failures == 2

    async def test_reaching_threshold_opens_circuit(self):
        cb = self._make_breaker(threshold=3)

        async def _fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.async_call(_fail)

        assert cb.state.state == "open"

    async def test_open_circuit_blocks_calls(self):
        cb = self._make_breaker(threshold=1, base_seconds=100)

        async def _fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.async_call(_fail)

        assert cb.state.state == "open"

        with pytest.raises(RuntimeError, match="circuit_open"):
            await cb.async_call(lambda: asyncio.coroutine(lambda: "ok")())

    async def test_open_transitions_to_half_open_after_timeout(self):
        cb = self._make_breaker(threshold=1, base_seconds=0.01)

        async def _fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.async_call(_fail)

        assert cb.state.state == "open"

        # Wait for the open_seconds window to expire
        await asyncio.sleep(0.05)

        async def _recovered():
            return "recovered"

        result = await cb.async_call(_recovered)
        # After successful half-open probe the circuit closes
        assert cb.state.state == "closed"
        assert result == "recovered"

    async def test_half_open_failure_reopens_with_backoff(self):
        cb = self._make_breaker(threshold=1, base_seconds=0.01)

        async def _fail():
            raise ValueError("boom")

        # Trip to open
        with pytest.raises(ValueError):
            await cb.async_call(_fail)

        initial_open_seconds = cb.state.open_seconds

        # Wait for half-open window
        await asyncio.sleep(0.05)

        # Fail again in half-open — should re-open with increased backoff
        with pytest.raises(ValueError):
            await cb.async_call(_fail)

        assert cb.state.state == "open"
        assert cb.state.open_seconds >= initial_open_seconds

    async def test_success_in_closed_keeps_failures_zero(self):
        cb = self._make_breaker()

        async def _one():
            return 1

        for _ in range(5):
            await cb.async_call(_one)
        assert cb.state.failures == 0

    async def test_success_after_partial_failures_resets(self):
        """One failure then a success should reset the failure counter."""
        cb = self._make_breaker(threshold=5)

        async def _fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.async_call(_fail)

        assert cb.state.failures == 1

        async def _ok():
            return "ok"

        await cb.async_call(_ok)
        assert cb.state.failures == 0


# ---------------------------------------------------------------------------
# CircuitBreakerManager
# ---------------------------------------------------------------------------


class TestCircuitBreakerManager:
    def test_get_creates_new_breaker(self):
        mgr = CircuitBreakerManager()
        br = mgr.get("key-a")
        assert isinstance(br, CircuitBreaker)
        assert br.key == "key-a"

    def test_get_is_idempotent(self):
        mgr = CircuitBreakerManager()
        br1 = mgr.get("key-b")
        br2 = mgr.get("key-b")
        assert br1 is br2

    def test_different_keys_get_different_breakers(self):
        mgr = CircuitBreakerManager()
        a = mgr.get("a")
        b = mgr.get("b")
        assert a is not b

    def test_breakers_property(self):
        mgr = CircuitBreakerManager()
        mgr.get("x")
        mgr.get("y")
        assert set(mgr.breakers.keys()) == {"x", "y"}

    def test_snapshot_lists_keys(self):
        mgr = CircuitBreakerManager()
        mgr.get("k1")
        mgr.get("k2")
        snap = mgr.snapshot()
        assert set(snap["keys"]) == {"k1", "k2"}
        assert snap["open_count"] == 0
        assert snap["open_keys"] == []

    async def test_snapshot_reports_open_keys(self):
        mgr = CircuitBreakerManager()

        async def _fail():
            raise ValueError("boom")

        br = mgr.get("will-open")
        with patch.dict("os.environ", {"FORGE_CB_FAILURE_THRESHOLD": "1"}):
            br.failure_threshold = 1
        with pytest.raises(ValueError):
            await mgr.async_call("will-open", _fail)

        snap = mgr.snapshot()
        assert "will-open" in snap["open_keys"]
        assert snap["open_count"] == 1

    async def test_async_call_delegates_to_breaker(self):
        mgr = CircuitBreakerManager()

        async def _forty_two():
            return 42

        result = await mgr.async_call("test-key", _forty_two)
        assert result == 42


# ---------------------------------------------------------------------------
# _BreakerMetrics
# ---------------------------------------------------------------------------


class TestBreakerMetrics:
    def test_initial_counters_are_zero(self):
        m = _BreakerMetrics()
        snap = m.snapshot()
        assert snap["opens_total"] == 0
        assert snap["blocked_total"] == 0
        assert snap["half_open_probes_total"] == 0
        assert snap["close_success_total"] == 0

    def test_on_open_increments(self):
        m = _BreakerMetrics()
        m.on_open("k")
        m.on_open("k")
        assert m.snapshot()["opens_total"] == 2

    def test_on_blocked_increments(self):
        m = _BreakerMetrics()
        m.on_blocked("k")
        assert m.snapshot()["blocked_total"] == 1

    def test_on_half_open_probe_increments(self):
        m = _BreakerMetrics()
        m.on_half_open_probe("k")
        assert m.snapshot()["half_open_probes_total"] == 1

    def test_on_close_success_increments(self):
        m = _BreakerMetrics()
        m.on_close_success("k")
        assert m.snapshot()["close_success_total"] == 1


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestModuleHelpers:
    def test_get_circuit_breaker_metrics_snapshot_returns_dict(self):
        snap = get_circuit_breaker_metrics_snapshot()
        assert "opens_total" in snap
        assert "blocked_total" in snap
        assert "open_keys" in snap
        assert "open_count" in snap
