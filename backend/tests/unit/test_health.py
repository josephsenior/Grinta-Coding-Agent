"""Unit tests for backend.controller.health — System health checks."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.controller.health import (
    CircuitBreakerHealth,
    ServiceHealth,
    check_system_health,
    collect_controller_health,
    get_mini_health_report,
)


# ---------------------------------------------------------------------------
# CircuitBreakerHealth dataclass
# ---------------------------------------------------------------------------


class TestCircuitBreakerHealth:
    def test_defaults(self):
        h = CircuitBreakerHealth(name="test", state="closed", failure_count=0)
        assert h.name == "test"
        assert h.state == "closed"
        assert h.failure_count == 0
        assert h.last_failure_time is None

    def test_with_failure_time(self):
        now = datetime.now(UTC)
        h = CircuitBreakerHealth(
            name="llm", state="open", failure_count=5, last_failure_time=now
        )
        assert h.last_failure_time == now


# ---------------------------------------------------------------------------
# ServiceHealth dataclass
# ---------------------------------------------------------------------------


class TestServiceHealth:
    def test_defaults(self):
        h = ServiceHealth(
            status="healthy",
            version="1.0.0",
            uptime_seconds=60.0,
            circuit_breakers=[],
        )
        assert h.metrics_synced is True
        assert h.event_stream_connected is True

    def test_with_breakers(self):
        br = CircuitBreakerHealth(name="test", state="closed", failure_count=0)
        h = ServiceHealth(
            status="healthy",
            version="1.0.0",
            uptime_seconds=100.0,
            circuit_breakers=[br],
        )
        assert len(h.circuit_breakers) == 1


# ---------------------------------------------------------------------------
# get_mini_health_report
# ---------------------------------------------------------------------------


class TestMiniHealthReport:
    def test_returns_dict(self):
        report = get_mini_health_report()
        assert isinstance(report, dict)
        assert report["status"] == "healthy"
        assert "version" in report
        assert "timestamp" in report

    def test_timestamp_is_iso(self):
        report = get_mini_health_report()
        # Should be a valid ISO timestamp
        datetime.fromisoformat(report["timestamp"])


# ---------------------------------------------------------------------------
# check_system_health
# ---------------------------------------------------------------------------


class TestCheckSystemHealth:
    @pytest.mark.asyncio
    async def test_returns_service_health(self):
        result = await check_system_health()
        assert isinstance(result, ServiceHealth)
        assert result.status in ("healthy", "degraded")
        assert "version" in result.__dict__ or hasattr(result, "version")

    @pytest.mark.asyncio
    async def test_healthy_when_no_open_breakers(self):
        result = await check_system_health()
        # Default state: no breakers registered → healthy
        assert result.status == "healthy"


# ---------------------------------------------------------------------------
# collect_controller_health
# ---------------------------------------------------------------------------


class TestCollectControllerHealth:
    def _make_controller(
        self,
        agent_state="running",
        iteration_current=5,
        iteration_max=100,
        budget_current=0.5,
        budget_max=10.0,
        accumulated_cost=1.5,
        cb_state_name=None,
        cb_failures=0,
        pending_retry=False,
    ):
        ctrl = MagicMock()
        ctrl.sid = "test-session-id"

        # state.agent_state
        state_obj = MagicMock()
        state_obj.agent_state = MagicMock(value=agent_state)

        # iteration_flag
        state_obj.iteration_flag = MagicMock(
            current_value=iteration_current,
            max_value=iteration_max,
        )

        # budget_flag
        state_obj.budget_flag = MagicMock(
            current_value=budget_current,
            max_value=budget_max,
        )

        # metrics
        state_obj.metrics = MagicMock(accumulated_cost=accumulated_cost)

        ctrl.state = state_obj

        # circuit_breaker_service
        if cb_state_name:
            cb_service = MagicMock()
            cb_service.state = MagicMock(name=cb_state_name)
            cb_service.state.name = cb_state_name
            cb_service.failure_count = cb_failures
        else:
            cb_service = None
        ctrl.circuit_breaker_service = cb_service

        # retry_service
        retry_service = MagicMock()
        retry_service.pending_retry = pending_retry
        ctrl.retry_service = retry_service

        return ctrl

    def test_healthy_controller(self):
        ctrl = self._make_controller()
        h = collect_controller_health(ctrl)
        assert h["severity"] == "green"
        assert h["warnings"] == []
        assert h["controller_id"] == "test-session-id"
        assert h["state"]["agent_state"] == "running"
        assert h["state"]["iteration"]["current"] == 5
        assert h["state"]["iteration"]["max"] == 100
        assert h["state"]["budget"]["current"] == 0.5
        assert h["state"]["budget"]["max"] == 10.0
        assert h["state"]["accumulated_cost"] == 1.5

    def test_cb_open_severity_red(self):
        ctrl = self._make_controller(cb_state_name="OPEN", cb_failures=5)
        h = collect_controller_health(ctrl)
        assert h["severity"] == "red"
        assert "circuit_breaker_unhealthy" in h["warnings"]

    def test_cb_failures_high_severity_yellow(self):
        ctrl = self._make_controller(cb_state_name="CLOSED", cb_failures=5)
        h = collect_controller_health(ctrl)
        assert h["severity"] == "yellow"
        assert "circuit_breaker_unhealthy" in h["warnings"]

    def test_retry_pending_warning(self):
        ctrl = self._make_controller(pending_retry=True)
        h = collect_controller_health(ctrl)
        assert "retry_pending" in h["warnings"]
        assert h["severity"] == "yellow"

    def test_multiple_warnings(self):
        ctrl = self._make_controller(
            cb_state_name="CLOSED", cb_failures=6, pending_retry=True
        )
        h = collect_controller_health(ctrl)
        assert "circuit_breaker_unhealthy" in h["warnings"]
        assert "retry_pending" in h["warnings"]

    def test_timestamp_present(self):
        ctrl = self._make_controller()
        h = collect_controller_health(ctrl)
        assert "timestamp" in h
        datetime.fromisoformat(h["timestamp"])

    def test_no_cb_service(self):
        ctrl = self._make_controller(cb_state_name=None)
        h = collect_controller_health(ctrl)
        # Should not crash; severity stays green
        assert h["severity"] == "green"

    def test_no_retry_service(self):
        ctrl = self._make_controller()
        ctrl.retry_service = None
        h = collect_controller_health(ctrl)
        assert h["severity"] == "green"
