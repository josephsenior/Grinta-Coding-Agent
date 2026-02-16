"""Unit tests for backend.controller.agent_circuit_breaker — autonomous safety."""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

import pytest

from backend.controller.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerResult,
)
from backend.events.action import ActionSecurityRisk
from backend.events.observation import ErrorObservation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(history=None):
    state = MagicMock()
    state.history = history or []
    return state


def _make_cb(**overrides) -> CircuitBreaker:
    defaults = dict(
        enabled=True,
        max_consecutive_errors=3,
        max_high_risk_actions=5,
        max_stuck_detections=2,
        max_error_rate=0.5,
        error_rate_window=6,
    )
    defaults.update(overrides)
    return CircuitBreaker(CircuitBreakerConfig(**defaults))


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


class TestCircuitBreakerConfig:
    def test_defaults(self):
        cfg = CircuitBreakerConfig()
        assert cfg.enabled is True
        assert cfg.max_consecutive_errors == 5
        assert cfg.max_high_risk_actions == 10
        assert cfg.max_stuck_detections == 3
        assert cfg.max_error_rate == 0.5
        assert cfg.error_rate_window == 10

    def test_custom(self):
        cfg = CircuitBreakerConfig(max_consecutive_errors=2, enabled=False)
        assert cfg.max_consecutive_errors == 2
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


class TestCircuitBreakerResult:
    def test_not_tripped(self):
        r = CircuitBreakerResult(tripped=False, reason="ok", action="continue")
        assert r.tripped is False
        assert r.recommendation == ""

    def test_tripped(self):
        r = CircuitBreakerResult(
            tripped=True, reason="errors", action="pause", recommendation="fix it"
        )
        assert r.tripped is True
        assert r.action == "pause"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_counters_zeroed(self):
        cb = _make_cb()
        assert cb.consecutive_errors == 0
        assert cb.high_risk_action_count == 0
        assert cb.stuck_detection_count == 0

    def test_deques_empty(self):
        cb = _make_cb()
        assert len(cb.recent_errors) == 0
        assert len(cb.recent_actions_success) == 0


# ---------------------------------------------------------------------------
# Disabled circuit breaker
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_disabled_never_trips(self):
        cb = _make_cb(enabled=False)
        # Even with lots of errors
        for _ in range(20):
            cb.record_error(RuntimeError("fail"))
        result = cb.check(_make_state())
        assert result.tripped is False
        assert result.action == "continue"


# ---------------------------------------------------------------------------
# Consecutive errors
# ---------------------------------------------------------------------------


class TestConsecutiveErrors:
    def test_trips_at_threshold(self):
        cb = _make_cb(max_consecutive_errors=3)
        for _ in range(3):
            cb.record_error(RuntimeError("fail"))
        result = cb.check(_make_state())
        assert result.tripped is True
        assert "consecutive errors" in result.reason.lower()
        assert result.action == "pause"

    def test_below_threshold_ok(self):
        cb = _make_cb(max_consecutive_errors=3)
        cb.record_error(RuntimeError("fail"))
        cb.record_error(RuntimeError("fail"))
        result = cb.check(_make_state())
        assert result.tripped is False

    def test_success_resets_counter(self):
        cb = _make_cb(max_consecutive_errors=3)
        cb.record_error(RuntimeError("fail"))
        cb.record_error(RuntimeError("fail"))
        cb.record_success()
        assert cb.consecutive_errors == 0
        cb.record_error(RuntimeError("fail"))
        result = cb.check(_make_state())
        assert result.tripped is False


# ---------------------------------------------------------------------------
# High-risk actions
# ---------------------------------------------------------------------------


class TestHighRiskActions:
    def test_trips_at_threshold(self):
        cb = _make_cb(max_high_risk_actions=3)
        for _ in range(3):
            cb.record_high_risk_action(ActionSecurityRisk.HIGH)
        result = cb.check(_make_state())
        assert result.tripped is True
        assert "high-risk" in result.reason.lower()

    def test_non_high_risk_ignored(self):
        cb = _make_cb(max_high_risk_actions=3)
        for _ in range(10):
            cb.record_high_risk_action(ActionSecurityRisk.LOW)
        result = cb.check(_make_state())
        assert result.tripped is False

    def test_medium_risk_ignored(self):
        cb = _make_cb(max_high_risk_actions=3)
        for _ in range(10):
            cb.record_high_risk_action(ActionSecurityRisk.MEDIUM)
        assert cb.high_risk_action_count == 0


# ---------------------------------------------------------------------------
# Stuck detection
# ---------------------------------------------------------------------------


class TestStuckDetection:
    def test_trips_at_threshold(self):
        cb = _make_cb(max_stuck_detections=2)
        cb.record_stuck_detection()
        cb.record_stuck_detection()
        result = cb.check(_make_state())
        assert result.tripped is True
        assert "stuck" in result.reason.lower()
        assert result.action == "stop"

    def test_below_threshold_ok(self):
        cb = _make_cb(max_stuck_detections=3)
        cb.record_stuck_detection()
        result = cb.check(_make_state())
        assert result.tripped is False


# ---------------------------------------------------------------------------
# Error rate
# ---------------------------------------------------------------------------


class TestErrorRate:
    def test_high_error_rate_trips(self):
        cb = _make_cb(max_error_rate=0.5, error_rate_window=6)
        # 4 failures, 2 successes => 67% error rate in window of 6
        for _ in range(4):
            cb.record_error(RuntimeError("fail"))
        for _ in range(2):
            cb.record_success()
        result = cb.check(_make_state())
        assert result.tripped is True
        assert "error rate" in result.reason.lower()

    def test_low_error_rate_ok(self):
        cb = _make_cb(max_error_rate=0.5, error_rate_window=10)
        cb.record_error(RuntimeError("fail"))
        for _ in range(9):
            cb.record_success()
        result = cb.check(_make_state())
        assert result.tripped is False

    def test_insufficient_window_no_trip(self):
        """Error rate not checked until window is full."""
        cb = _make_cb(max_error_rate=0.5, error_rate_window=10)
        # Only 3 actions (all errors) but window requires 10
        for _ in range(3):
            cb.record_error(RuntimeError("fail"))
        result = cb.check(_make_state())
        # consecutive_errors trips first (default 3) — let's use a higher threshold
        cb2 = _make_cb(max_error_rate=0.5, error_rate_window=10, max_consecutive_errors=100)
        for _ in range(3):
            cb2.record_error(RuntimeError("fail"))
        result2 = cb2.check(_make_state())
        assert result2.tripped is False

    def test_calculate_error_rate_empty(self):
        cb = _make_cb()
        assert cb._calculate_error_rate() == 0.0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all(self):
        cb = _make_cb()
        cb.record_error(RuntimeError("fail"))
        cb.record_high_risk_action(ActionSecurityRisk.HIGH)
        cb.record_stuck_detection()
        cb.reset()
        assert cb.consecutive_errors == 0
        assert cb.high_risk_action_count == 0
        assert cb.stuck_detection_count == 0
        assert len(cb.recent_errors) == 0
        assert len(cb.recent_actions_success) == 0


# ---------------------------------------------------------------------------
# Priority ordering (which trip condition fires first)
# ---------------------------------------------------------------------------


class TestPriorityOrder:
    def test_consecutive_errors_before_error_rate(self):
        """Consecutive errors are checked before error rate."""
        cb = _make_cb(max_consecutive_errors=2, max_error_rate=0.5, error_rate_window=4)
        for _ in range(3):
            cb.record_error(RuntimeError("fail"))
        result = cb.check(_make_state())
        assert "consecutive errors" in result.reason.lower()

    def test_stuck_is_stop_action(self):
        """Stuck detection results in 'stop', not 'pause'."""
        cb = _make_cb(max_stuck_detections=1)
        cb.record_stuck_detection()
        result = cb.check(_make_state())
        assert result.action == "stop"


# ---------------------------------------------------------------------------
# _update_metrics from state
# ---------------------------------------------------------------------------


class TestUpdateMetrics:
    def test_error_observations_counted(self):
        cb = _make_cb()
        errors = [ErrorObservation(content=f"err {i}") for i in range(3)]
        state = _make_state(history=errors)
        cb._update_metrics(state)
        # Should have recorded errors
        assert cb.consecutive_errors >= 3
