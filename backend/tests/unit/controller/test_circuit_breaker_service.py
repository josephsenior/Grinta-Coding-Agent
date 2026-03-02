"""Tests for backend.controller.services.circuit_breaker_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from typing import cast


from backend.controller.services.circuit_breaker_service import CircuitBreakerService
from backend.core.config import AgentConfig


def _make_context() -> MagicMock:
    controller = MagicMock()
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    return ctx


# ── init / reset ─────────────────────────────────────────────────────


class TestInit:
    def test_initial_state(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        assert svc.circuit_breaker is None

    def test_reset_clears_breaker(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        svc._circuit_breaker = MagicMock()
        svc.reset()
        assert svc._circuit_breaker is None


# ── configure ────────────────────────────────────────────────────────


class TestConfigure:
    def test_configure_creates_circuit_breaker(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        config = SimpleNamespace(
            enable_circuit_breaker=True,
            max_consecutive_errors=7,
            max_high_risk_actions=12,
            max_stuck_detections=5,
        )
        svc.configure(cast(AgentConfig, config))
        assert svc.circuit_breaker is not None

    def test_configure_disabled(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        config = SimpleNamespace(enable_circuit_breaker=False)
        svc.configure(cast(AgentConfig, config))
        assert svc.circuit_breaker is None

    def test_configure_uses_defaults_for_missing_attrs(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        config = SimpleNamespace(enable_circuit_breaker=True)
        svc.configure(cast(AgentConfig, config))
        assert svc.circuit_breaker is not None


# ── check ────────────────────────────────────────────────────────────


class TestCheck:
    def test_check_returns_none_without_breaker(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        assert svc.check() is None

    def test_check_delegates_to_breaker(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        mock_cb = MagicMock()
        mock_cb.check.return_value = "tripped"
        svc._circuit_breaker = mock_cb
        result = svc.check()
        assert result == "tripped"
        mock_cb.check.assert_called_once()


# ── record_error / record_success / record_high_risk / record_stuck ─


class TestRecording:
    def test_record_error_with_breaker(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        mock_cb = MagicMock()
        svc._circuit_breaker = mock_cb
        exc = RuntimeError("boom")
        svc.record_error(exc)
        mock_cb.record_error.assert_called_once_with(exc)

    def test_record_error_without_breaker_noop(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        svc.record_error(RuntimeError("ok"))  # no error

    def test_record_success(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        mock_cb = MagicMock()
        svc._circuit_breaker = mock_cb
        svc.record_success()
        mock_cb.record_success.assert_called_once()

    def test_record_success_without_breaker_noop(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        svc.record_success()  # no error

    def test_record_high_risk_action(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        mock_cb = MagicMock()
        svc._circuit_breaker = mock_cb
        svc.record_high_risk_action("HIGH")
        mock_cb.record_high_risk_action.assert_called_once_with("HIGH")

    def test_record_high_risk_action_none_skips(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        mock_cb = MagicMock()
        svc._circuit_breaker = mock_cb
        svc.record_high_risk_action(None)
        mock_cb.record_high_risk_action.assert_not_called()

    def test_record_stuck_detection(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        mock_cb = MagicMock()
        svc._circuit_breaker = mock_cb
        svc.record_stuck_detection()
        mock_cb.record_stuck_detection.assert_called_once()

    def test_record_stuck_without_breaker_noop(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        svc.record_stuck_detection()  # no error


# ── controller property ──────────────────────────────────────────────


class TestControllerProperty:
    def test_controller_returns_from_context(self):
        ctx = _make_context()
        svc = CircuitBreakerService(ctx)
        assert svc.controller is ctx.get_controller()
