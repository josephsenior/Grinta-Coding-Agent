"""Tests for backend.orchestration.health module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.orchestration.health import (
    CircuitBreakerHealth,
    ServiceHealth,
    check_circuit_breaker_health,
    check_system_health,
    collect_orchestration_health,
    get_circuit_breaker_stats,
    get_event_stream_stats,
    get_mini_health_report,
    is_system_stuck,
    sync_state_metrics,
)


class TestCircuitBreakerHealth:
    """Tests for CircuitBreakerHealth dataclass."""

    def test_create_with_required_fields(self):
        """Test creating with required fields only."""
        health = CircuitBreakerHealth(
            name="test_breaker",
            state="CLOSED",
            failure_count=0,
        )
        assert health.name == "test_breaker"
        assert health.state == "CLOSED"
        assert health.failure_count == 0
        assert health.last_failure_time is None

    def test_create_with_all_fields(self):
        """Test creating with all fields."""
        now = datetime.now(UTC)
        health = CircuitBreakerHealth(
            name="test_breaker",
            state="OPEN",
            failure_count=5,
            last_failure_time=now,
        )
        assert health.name == "test_breaker"
        assert health.state == "OPEN"
        assert health.failure_count == 5
        assert health.last_failure_time == now


class TestServiceHealth:
    """Tests for ServiceHealth dataclass."""

    def test_create_with_required_fields(self):
        """Test creating with required fields."""
        health = ServiceHealth(
            status="healthy",
            version="1.0.0",
            uptime_seconds=100.5,
            circuit_breakers=[],
        )
        assert health.status == "healthy"
        assert health.version == "1.0.0"
        assert health.uptime_seconds == 100.5
        assert health.circuit_breakers == []
        assert health.metrics_synced is True
        assert health.event_stream_connected is True

    def test_create_with_custom_flags(self):
        """Test creating with custom boolean flags."""
        breaker = CircuitBreakerHealth("test", "CLOSED", 0)
        health = ServiceHealth(
            status="degraded",
            version="1.0.0",
            uptime_seconds=50.0,
            circuit_breakers=[breaker],
            metrics_synced=False,
            event_stream_connected=False,
        )
        assert health.status == "degraded"
        assert health.metrics_synced is False
        assert health.event_stream_connected is False


class TestGetCircuitBreakerStats:
    """Tests for get_circuit_breaker_stats function."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_breakers(self):
        """Test returns empty list when no breakers registered."""
        mock_manager = MagicMock()
        mock_manager.breakers = {}

        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            return_value=mock_manager,
        ):
            result = await get_circuit_breaker_stats()
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_breaker_stats(self):
        """Test returns statistics for registered breakers."""
        mock_state = MagicMock()
        mock_state.name = "CLOSED"

        mock_breaker = MagicMock()
        mock_breaker.state = mock_state
        mock_breaker.failure_count = 3
        mock_breaker.last_failure_time = None

        mock_manager = MagicMock()
        mock_manager.breakers = {"api_breaker": mock_breaker}

        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            return_value=mock_manager,
        ):
            result = await get_circuit_breaker_stats()
            assert len(result) == 1
            assert result[0].name == "api_breaker"
            assert result[0].state == "CLOSED"
            assert result[0].failure_count == 3

    @pytest.mark.asyncio
    async def test_handles_import_error(self):
        """Test returns empty list on ImportError."""
        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            side_effect=ImportError,
        ):
            result = await get_circuit_breaker_stats()
            assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_attributes(self):
        """Test handles breakers with missing attributes gracefully."""
        mock_breaker = MagicMock()
        del mock_breaker.state
        del mock_breaker.failure_count
        del mock_breaker.last_failure_time

        mock_manager = MagicMock()
        mock_manager.breakers = {"incomplete_breaker": mock_breaker}

        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            return_value=mock_manager,
        ):
            result = await get_circuit_breaker_stats()
            assert len(result) == 1
            # Should use getattr with defaults
            assert result[0].failure_count == 0


class TestCheckSystemHealth:
    """Tests for check_system_health function."""

    @pytest.mark.asyncio
    async def test_returns_healthy_status_with_no_issues(self):
        """Test returns healthy status when all checks pass."""
        with (
            patch("backend.__version__", "1.2.3"),
            patch(
                "backend.orchestration.health.get_circuit_breaker_stats",
                return_value=[],
            ),
        ):
            result = await check_system_health()
            assert result.status == "healthy"
            assert result.version == "1.2.3"
            assert result.event_stream_connected is True

    @pytest.mark.asyncio
    async def test_returns_degraded_when_breaker_open(self):
        """Test returns degraded status when circuit breaker is open."""
        breaker = CircuitBreakerHealth("api", "OPEN", 10)

        with (
            patch("backend.__version__", "1.0.0"),
            patch(
                "backend.orchestration.health.get_circuit_breaker_stats",
                return_value=[breaker],
            ),
        ):
            result = await check_system_health()
            assert result.status == "degraded"
            assert len(result.circuit_breakers) == 1
            assert result.circuit_breakers[0].state == "OPEN"

    @pytest.mark.asyncio
    async def test_includes_circuit_breaker_list(self):
        """Test includes circuit breaker information."""
        breakers = [
            CircuitBreakerHealth("api", "CLOSED", 0),
            CircuitBreakerHealth("db", "HALF_OPEN", 3),
        ]

        with (
            patch("backend.__version__", "1.0.0"),
            patch(
                "backend.orchestration.health.get_circuit_breaker_stats",
                return_value=breakers,
            ),
        ):
            result = await check_system_health()
            assert len(result.circuit_breakers) == 2


class TestGetMiniHealthReport:
    """Tests for get_mini_health_report function."""

    def test_returns_basic_health_info(self):
        """Test returns minimal health report."""
        with patch("backend.__version__", "2.0.0"):
            result = get_mini_health_report()
            assert result["status"] == "healthy"
            assert result["version"] == "2.0.0"
            assert "timestamp" in result

    def test_timestamp_format(self):
        """Test timestamp is in ISO format."""
        with patch("backend.__version__", "1.0.0"):
            result = get_mini_health_report()
            # Should be a valid ISO timestamp
            timestamp = datetime.fromisoformat(result["timestamp"])
            assert isinstance(timestamp, datetime)


class TestCheckCircuitBreakerHealth:
    """Tests for check_circuit_breaker_health function."""

    @pytest.mark.asyncio
    async def test_returns_breaker_status_when_found(self):
        """Test returns breaker status when found."""
        mock_state = MagicMock()
        mock_state.name = "CLOSED"

        mock_breaker = MagicMock()
        mock_breaker.state = mock_state
        mock_breaker.failure_count = 2
        mock_breaker.last_failure_time = None

        mock_manager = MagicMock()
        mock_manager.breakers = {"test_breaker": mock_breaker}

        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            return_value=mock_manager,
        ):
            result = await check_circuit_breaker_health("test_breaker")
            assert result["name"] == "test_breaker"
            assert result["state"] == "CLOSED"
            assert result["failures"] == 2

    @pytest.mark.asyncio
    async def test_returns_not_found_when_missing(self):
        """Test returns not_found status when breaker doesn't exist."""
        mock_manager = MagicMock()
        mock_manager.breakers = {}

        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            return_value=mock_manager,
        ):
            result = await check_circuit_breaker_health("missing_breaker")
            assert result["status"] == "not_found"
            assert result["name"] == "missing_breaker"

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        """Test handles exceptions and returns UNKNOWN."""
        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            side_effect=Exception("test error"),
        ):
            result = await check_circuit_breaker_health("any_breaker")
            assert result["name"] == "any_breaker"
            assert result["state"] == "UNKNOWN"
            assert result["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_includes_last_failure_time_when_present(self):
        """Test includes last failure time in ISO format."""
        now = datetime.now(UTC)
        mock_state = MagicMock()
        mock_state.name = "OPEN"

        mock_breaker = MagicMock()
        mock_breaker.state = mock_state
        mock_breaker.failure_count = 5
        mock_breaker.last_failure_time = now

        mock_manager = MagicMock()
        mock_manager.breakers = {"failing_breaker": mock_breaker}

        with patch(
            "backend.utils.circuit_breaker.get_circuit_breaker_manager",
            return_value=mock_manager,
        ):
            result = await check_circuit_breaker_health("failing_breaker")
            assert result["last_failure"] == now.isoformat()


class TestSyncStateMetrics:
    """Tests for sync_state_metrics function."""

    @pytest.mark.asyncio
    async def test_returns_true(self):
        """Test returns True indicating success."""
        result = await sync_state_metrics()
        assert result is True


class TestGetEventStreamStats:
    """Tests for get_event_stream_stats function."""

    @pytest.mark.asyncio
    async def test_returns_placeholder_stats(self):
        """Test returns placeholder stats."""
        result = await get_event_stream_stats()
        assert result["status"] == "no_stats_available"


class TestIsSystemStuck:
    """Tests for is_system_stuck function."""

    @pytest.mark.asyncio
    async def test_returns_false(self):
        """Test returns False by default."""
        result = await is_system_stuck()
        assert result is False


class TestCollectControllerHealth:
    """Tests for collect_orchestration_health function."""

    def test_basic_health_snapshot(self):
        """Test collects basic health snapshot."""
        mock_controller = MagicMock()
        mock_controller.sid = "test_session_123"

        # Mock state
        mock_state = MagicMock()
        mock_state.agent_state.value = "running"
        mock_controller.state = mock_state

        # Mock flags
        mock_iteration = MagicMock()
        mock_iteration.current_value = 5
        mock_iteration.max_value = 100
        mock_state.iteration_flag = mock_iteration

        mock_budget = MagicMock()
        mock_budget.current_value = 100
        mock_budget.max_value = 1000
        mock_state.budget_flag = mock_budget

        # Mock metrics
        mock_metrics = MagicMock()
        mock_metrics.accumulated_cost = 0.50
        mock_state.metrics = mock_metrics

        # Mock circuit breaker
        mock_cb_state = MagicMock()
        mock_cb_state.name = "CLOSED"
        mock_cb = MagicMock()
        mock_cb.state = mock_cb_state
        mock_cb.failure_count = 0
        mock_controller.circuit_breaker_service = mock_cb

        # Mock retry service
        mock_retry = MagicMock()
        mock_retry.pending_retry = False
        mock_controller.retry_service = mock_retry

        result = collect_orchestration_health(mock_controller)

        assert result["controller_id"] == "test_session_123"
        assert result["severity"] == "green"
        assert result["state"]["agent_state"] == "running"
        assert result["state"]["iteration"]["current"] == 5
        assert result["state"]["iteration"]["max"] == 100

    def test_yellow_severity_with_warnings(self):
        """Test returns yellow severity when warnings present."""
        mock_controller = MagicMock()
        mock_state = MagicMock()
        mock_controller.state = mock_state

        # Mock retry with pending
        mock_retry = MagicMock()
        mock_retry.pending_retry = True
        mock_controller.retry_service = mock_retry

        # Mock circuit breaker (healthy)
        mock_cb = MagicMock()
        mock_cb.state.name = "CLOSED"
        mock_cb.failure_count = 2
        mock_controller.circuit_breaker_service = mock_cb

        # Set required attributes
        mock_state.agent_state.value = "running"
        mock_state.iteration_flag.current_value = 1
        mock_state.iteration_flag.max_value = 10
        mock_state.budget_flag.current_value = 10
        mock_state.budget_flag.max_value = 100
        mock_state.metrics.accumulated_cost = 0.1

        result = collect_orchestration_health(mock_controller)

        assert result["severity"] == "yellow"
        assert "retry_pending" in result["warnings"]

    def test_red_severity_with_circuit_breaker_open(self):
        """Test returns red severity when circuit breaker open."""
        mock_controller = MagicMock()
        mock_state = MagicMock()
        mock_controller.state = mock_state

        # Mock circuit breaker (open)
        mock_cb_state = MagicMock()
        mock_cb_state.name = "OPEN"
        mock_cb = MagicMock()
        mock_cb.state = mock_cb_state
        mock_cb.failure_count = 10
        mock_controller.circuit_breaker_service = mock_cb

        # Mock retry
        mock_retry = MagicMock()
        mock_retry.pending_retry = False
        mock_controller.retry_service = mock_retry

        # Set required attributes
        mock_state.agent_state.value = "error"
        mock_state.iteration_flag.current_value = 50
        mock_state.iteration_flag.max_value = 100
        mock_state.budget_flag.current_value = 800
        mock_state.budget_flag.max_value = 1000
        mock_state.metrics.accumulated_cost = 5.0

        result = collect_orchestration_health(mock_controller)

        assert result["severity"] == "red"
        assert "circuit_breaker_open" in result["warnings"]

    def test_handles_missing_attributes_gracefully(self):
        """Test handles missing attributes with defaults."""
        mock_controller = MagicMock()
        # Remove most attributes
        del mock_controller.state
        del mock_controller.circuit_breaker_service
        del mock_controller.retry_service

        result = collect_orchestration_health(mock_controller)

        # Should still return a valid result with unknowns
        assert "timestamp" in result
        assert result["state"]["agent_state"] == "unknown"
        assert result["severity"] in ["green", "yellow", "red"]

    def test_includes_timestamp(self):
        """Test includes ISO timestamp."""
        mock_controller = MagicMock()
        mock_state = MagicMock()
        mock_controller.state = mock_state

        # Mock circuit breaker
        mock_cb = MagicMock()
        mock_cb.state.name = "CLOSED"
        mock_cb.failure_count = 0
        mock_controller.circuit_breaker_service = mock_cb

        # Mock retry
        mock_retry = MagicMock()
        mock_retry.pending_retry = False
        mock_controller.retry_service = mock_retry

        # Set required attributes
        mock_state.agent_state.value = "running"
        mock_state.iteration_flag.current_value = 1
        mock_state.iteration_flag.max_value = 10
        mock_state.budget_flag.current_value = 10
        mock_state.budget_flag.max_value = 100
        mock_state.metrics.accumulated_cost = 0.1

        result = collect_orchestration_health(mock_controller)

        assert "timestamp" in result
        # Verify it's a valid ISO timestamp
        timestamp = datetime.fromisoformat(result["timestamp"])
        assert isinstance(timestamp, datetime)
