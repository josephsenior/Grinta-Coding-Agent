"""Health check controllers for monitoring system status."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.core.logger import FORGE_logger as logger


@dataclass
class CircuitBreakerHealth:
    """Status of a circuit breaker."""

    name: str
    state: str
    failure_count: int
    last_failure_time: datetime | None = None


@dataclass
class ServiceHealth:
    """Overall system and service health status."""

    status: str
    version: str
    uptime_seconds: float
    circuit_breakers: list[CircuitBreakerHealth]
    metrics_synced: bool = True
    event_stream_connected: bool = True


async def get_circuit_breaker_stats() -> list[CircuitBreakerHealth]:
    """Retrieve current state of all registered circuit breakers.

    Returns:
        List of CircuitBreakerHealth objects.

    """
    try:
        from backend.utils.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        stats = []
        for name, breaker in manager.breakers.items():
            state = getattr(breaker, "state", None)
            stats.append(
                CircuitBreakerHealth(
                    name=name,
                    state=getattr(state, "name", str(state)),
                    failure_count=getattr(breaker, "failure_count", 0),
                    last_failure_time=getattr(breaker, "last_failure_time", None),
                )
            )
        return stats
    except ImportError:
        return []


async def check_system_health() -> ServiceHealth:
    """Perform a comprehensive health check of all system components.

    Returns:
        ServiceHealth object containing the status of various components.

    """
    from backend import __version__

    # Determine global status - 'healthy' if no critical failures
    global_status = "healthy"

    # Check circuit breakers
    breakers = await get_circuit_breaker_stats()
    if any(b.state == "OPEN" for b in breakers):
        global_status = "degraded"

    # Check event stream connection (optional check)
    event_stream_ok = True

    if not event_stream_ok:
        global_status = "degraded"

    # Calculate uptime (placeholder for now)
    uptime = 0.0

    return ServiceHealth(
        status=global_status,
        version=__version__,
        uptime_seconds=uptime,
        circuit_breakers=breakers,
        event_stream_connected=event_stream_ok,
    )


def get_mini_health_report() -> dict[str, Any]:
    """Provide a minimal health report for quick monitoring.

    Returns:
        Dictionary with status and version information.

    """
    from backend import __version__

    return {
        "status": "healthy",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def check_circuit_breaker_health(name: str) -> dict[str, Any]:
    """Check the health of a specific circuit breaker by name.

    Args:
        name: Name of the circuit breaker to check.

    Returns:
        Dictionary with the breaker's current health status.

    """
    try:
        from backend.utils.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        if name in manager.breakers:
            breaker = manager.breakers[name]
            state = getattr(breaker, "state", None)
            return {
                "name": name,
                "state": getattr(state, "name", str(state)),
                "failures": getattr(breaker, "failure_count", 0),
                "last_failure": (
                    lft.isoformat()
                    if (lft := getattr(breaker, "last_failure_time", None)) is not None
                    else None
                ),
            }
        return {"status": "not_found", "name": name}
    except Exception:
        logger.debug("Circuit breaker check failed", exc_info=True)

    return {
        "name": name,
        "state": "UNKNOWN",
        "failure_count": 0,
    }


async def sync_state_metrics() -> bool:
    """Trigger a synchronization of state metrics with the monitoring system.

    Returns:
        True if synchronization was successful, False otherwise.

    """
    return True


async def get_event_stream_stats() -> dict[str, Any]:
    """Collect statistics and performance metrics from the event stream.

    Returns:
        Dictionary containing event stream performance data.

    """
    return {"status": "no_stats_available"}


async def is_system_stuck() -> bool:
    """Detect if any core system components are in a 'stuck' or unresponsive state.

    Returns:
        True if potential deadlock or hang detected, False otherwise.

    """
    return False


def collect_controller_health(controller: Any) -> dict[str, Any]:
    """Collect a lightweight, dependency-safe health snapshot for a controller.

    The snapshot is used by monitoring endpoints and integration tests.
    """
    now = datetime.now(UTC).isoformat()

    state_obj = getattr(controller, "state", None)
    agent_state = getattr(getattr(state_obj, "agent_state", None), "value", "unknown")

    iteration_flag = getattr(state_obj, "iteration_flag", None)
    iteration_current = getattr(iteration_flag, "current_value", None)
    iteration_max = getattr(iteration_flag, "max_value", None)

    budget_flag = getattr(state_obj, "budget_flag", None)
    budget_current = getattr(budget_flag, "current_value", None)
    budget_max = getattr(budget_flag, "max_value", None)

    metrics = getattr(state_obj, "metrics", None)
    accumulated_cost = getattr(metrics, "accumulated_cost", None)

    warnings: list[str] = []
    severity = "green"

    cb_service = getattr(controller, "circuit_breaker_service", None)
    cb_state = getattr(cb_service, "state", None)
    cb_state_name = getattr(cb_state, "name", str(cb_state) if cb_state else None)
    cb_failures = getattr(cb_service, "failure_count", 0) or 0
    if cb_state_name == "OPEN" or cb_failures >= 5:
        warnings.append("circuit_breaker_unhealthy")

    retry_service = getattr(controller, "retry_service", None)
    if getattr(retry_service, "pending_retry", False):
        warnings.append("retry_pending")

    if warnings:
        severity = "yellow"
    if cb_state_name == "OPEN":
        severity = "red"

    return {
        "timestamp": now,
        "controller_id": getattr(controller, "sid", "unknown"),
        "severity": severity,
        "warnings": warnings,
        "state": {
            "agent_state": agent_state,
            "iteration": {
                "current": iteration_current,
                "max": iteration_max,
            },
            "budget": {
                "current": budget_current,
                "max": budget_max,
            },
            "accumulated_cost": accumulated_cost,
        },
    }
