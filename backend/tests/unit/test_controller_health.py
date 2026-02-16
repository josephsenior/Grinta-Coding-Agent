"""Tests for backend.controller.health module."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestCircuitBreakerHealth:
    def test_defaults(self):
        from backend.controller.health import CircuitBreakerHealth

        cbh = CircuitBreakerHealth(name="llm", state="CLOSED", failure_count=0)
        assert cbh.name == "llm"
        assert cbh.state == "CLOSED"
        assert cbh.failure_count == 0
        assert cbh.last_failure_time is None

    def test_with_failure_time(self):
        from backend.controller.health import CircuitBreakerHealth

        now = datetime.now(UTC)
        cbh = CircuitBreakerHealth(
            name="llm", state="OPEN", failure_count=3, last_failure_time=now
        )
        assert cbh.last_failure_time == now


class TestServiceHealth:
    def test_construction(self):
        from backend.controller.health import ServiceHealth

        sh = ServiceHealth(
            status="healthy",
            version="1.0.0",
            uptime_seconds=120.5,
            circuit_breakers=[],
        )
        assert sh.status == "healthy"
        assert sh.version == "1.0.0"
        assert sh.uptime_seconds == 120.5
        assert sh.metrics_synced is True
        assert sh.event_stream_connected is True


class TestGetMiniHealthReport:
    def test_returns_dict(self):
        from backend.controller.health import get_mini_health_report

        report = get_mini_health_report()
        assert report["status"] == "healthy"
        assert "version" in report
        assert "timestamp" in report


class TestCheckSystemHealth:
    @patch("backend.controller.health.get_circuit_breaker_stats", return_value=[])
    async def test_healthy_when_no_breakers(self, mock_stats):
        from backend.controller.health import check_system_health

        result = await check_system_health()
        assert result.status == "healthy"
        assert result.circuit_breakers == []

    @patch("backend.controller.health.get_circuit_breaker_stats")
    async def test_degraded_when_breaker_open(self, mock_stats):
        from backend.controller.health import CircuitBreakerHealth, check_system_health

        mock_stats.return_value = [
            CircuitBreakerHealth(name="llm", state="OPEN", failure_count=5)
        ]
        result = await check_system_health()
        assert result.status == "degraded"


class TestCollectControllerHealth:
    def test_healthy_controller(self):
        from backend.controller.health import collect_controller_health

        controller = MagicMock()
        controller.sid = "session-1"
        state = MagicMock()
        state.agent_state.value = "running"
        state.iteration_flag.current_value = 3
        state.iteration_flag.max_value = 100
        state.budget_flag.current_value = 0.5
        state.budget_flag.max_value = 10.0
        state.metrics.accumulated_cost = 0.5
        controller.state = state
        controller.circuit_breaker_service.state.name = "CLOSED"
        controller.circuit_breaker_service.failure_count = 0
        controller.retry_service.pending_retry = False

        result = collect_controller_health(controller)
        assert result["severity"] == "green"
        assert result["controller_id"] == "session-1"
        assert result["state"]["agent_state"] == "running"
        assert result["warnings"] == []

    def test_degraded_circuit_breaker(self):
        from backend.controller.health import collect_controller_health

        controller = MagicMock()
        controller.sid = "session-2"
        state = MagicMock()
        state.agent_state.value = "running"
        state.iteration_flag.current_value = 5
        state.iteration_flag.max_value = 100
        state.budget_flag.current_value = 1.0
        state.budget_flag.max_value = 10.0
        state.metrics.accumulated_cost = 1.0
        controller.state = state
        controller.circuit_breaker_service.state.name = "OPEN"
        controller.circuit_breaker_service.failure_count = 10
        controller.retry_service.pending_retry = False

        result = collect_controller_health(controller)
        assert result["severity"] == "red"
        assert "circuit_breaker_unhealthy" in result["warnings"]

    def test_retry_pending_warning(self):
        from backend.controller.health import collect_controller_health

        controller = MagicMock()
        controller.sid = "session-3"
        state = MagicMock()
        state.agent_state.value = "running"
        state.iteration_flag.current_value = 1
        state.iteration_flag.max_value = 100
        state.budget_flag.current_value = 0
        state.budget_flag.max_value = 10.0
        state.metrics.accumulated_cost = 0
        controller.state = state
        controller.circuit_breaker_service.state.name = "CLOSED"
        controller.circuit_breaker_service.failure_count = 0
        controller.retry_service.pending_retry = True

        result = collect_controller_health(controller)
        assert result["severity"] == "yellow"
        assert "retry_pending" in result["warnings"]

    def test_missing_attributes_handled(self):
        """Controller with missing attributes should not crash."""
        from backend.controller.health import collect_controller_health

        controller = SimpleNamespace(sid="x")
        # No state, no circuit_breaker_service, etc.
        result = collect_controller_health(controller)
        assert "severity" in result
        assert "state" in result


class TestSyncStateMetrics:
    async def test_returns_true(self):
        from backend.controller.health import sync_state_metrics

        assert await sync_state_metrics() is True


class TestIsSystemStuck:
    async def test_returns_false(self):
        from backend.controller.health import is_system_stuck

        assert await is_system_stuck() is False


class TestGetEventStreamStats:
    async def test_returns_dict(self):
        from backend.controller.health import get_event_stream_stats

        result = await get_event_stream_stats()
        assert "status" in result
