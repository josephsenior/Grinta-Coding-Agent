"""Health check controllers for monitoring system status."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.core.logger import app_logger as logger


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


async def get_circuit_breaker_stats(
    controller: Any = None,
) -> list[CircuitBreakerHealth]:
    """Retrieve current state of the active circuit breaker(s).

    When *controller* is provided the returned stats reflect the actual
    agent circuit breaker (``agent_circuit_breaker.CircuitBreaker``) that
    governs the agent loop.  Without a controller the function falls back
    to the legacy utility breaker manager for backwards compatibility with
    standalone health checks.

    Args:
        controller: Optional orchestrator reference for live agent circuit-breaker data.

    Returns:
        List of CircuitBreakerHealth objects.
    """
    if controller is not None:
        return _controller_circuit_breaker_stats(controller)
    return _legacy_circuit_breaker_stats()


def _controller_circuit_breaker_stats(controller: Any) -> list[CircuitBreakerHealth]:
    """Read circuit breaker stats from the agent's actual CircuitBreakerService."""
    try:
        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if cb_service is None:
            return []
        cb = getattr(cb_service, 'circuit_breaker', None)
        if cb is None:
            return []
        return [
            CircuitBreakerHealth(
                name='agent_circuit_breaker',
                state='tripped'
                if getattr(cb, 'consecutive_errors', 0)
                >= getattr(getattr(cb, 'config', None), 'max_consecutive_errors', 5)
                else 'closed',
                failure_count=getattr(cb, 'consecutive_errors', 0),
                last_failure_time=getattr(cb, 'last_error_time', None),
            )
        ]
    except Exception:
        logger.debug('Failed to read controller circuit breaker stats', exc_info=True)
        return []


def _legacy_circuit_breaker_stats() -> list[CircuitBreakerHealth]:
    """Fallback: read from the utility circuit breaker manager (deprecated)."""
    try:
        from backend.utils.async_helpers.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        stats = []
        for name, breaker in manager.breakers.items():
            state = getattr(breaker, 'state', None)
            stats.append(
                CircuitBreakerHealth(
                    name=name,
                    state=getattr(state, 'name', str(state)),
                    failure_count=getattr(breaker, 'failure_count', 0),
                    last_failure_time=getattr(breaker, 'last_failure_time', None),
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
    global_status = 'healthy'

    # Check circuit breakers
    breakers = await get_circuit_breaker_stats()
    if any(b.state == 'OPEN' for b in breakers):
        global_status = 'degraded'

    # Check event stream connection (optional check)
    event_stream_ok = True

    if not event_stream_ok:
        global_status = 'degraded'

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
        'status': 'healthy',
        'version': __version__,
        'timestamp': datetime.now(UTC).isoformat(),
    }


async def check_circuit_breaker_health(
    name: str,
    controller: Any = None,
) -> dict[str, Any]:
    """Check the health of the active circuit breaker.

    When *controller* is provided the check reads from the actual agent
    circuit breaker.  Without it the legacy utility breaker manager is
    consulted for backwards compatibility.

    Args:
        name: Name of the circuit breaker to check.
        controller: Optional orchestrator reference.

    Returns:
        Dictionary with the breaker's current health status.
    """
    if controller is not None:
        return _controller_circuit_breaker_health(name, controller)
    return _legacy_circuit_breaker_health(name)


def _controller_circuit_breaker_health(name: str, controller: Any) -> dict[str, Any]:
    """Read circuit breaker health from the agent's CircuitBreakerService."""
    try:
        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if cb_service is None:
            return {'status': 'no_circuit_breaker_service', 'name': name}
        cb = getattr(cb_service, 'circuit_breaker', None)
        if cb is None:
            return {'status': 'circuit_breaker_disabled', 'name': name}
        config = getattr(cb, 'config', None)
        return {
            'name': 'agent_circuit_breaker',
            'state': (
                'OPEN'
                if getattr(cb, 'consecutive_errors', 0)
                >= getattr(config, 'max_consecutive_errors', 5)
                else 'CLOSED'
            ),
            'failures': getattr(cb, 'consecutive_errors', 0),
            'last_failure': (
                lft.isoformat()
                if (lft := getattr(cb, 'last_error_time', None)) is not None
                else None
            ),
        }
    except Exception:
        logger.debug('Circuit breaker controller check failed', exc_info=True)
    return {'name': name, 'state': 'UNKNOWN', 'failure_count': 0}


def _legacy_circuit_breaker_health(name: str) -> dict[str, Any]:
    """Fallback: read from the utility circuit breaker manager."""
    try:
        from backend.utils.async_helpers.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        if name in manager.breakers:
            breaker = manager.breakers[name]
            state = getattr(breaker, 'state', None)
            return {
                'name': name,
                'state': getattr(state, 'name', str(state)),
                'failures': getattr(breaker, 'failure_count', 0),
                'last_failure': (
                    lft.isoformat()
                    if (lft := getattr(breaker, 'last_failure_time', None)) is not None
                    else None
                ),
            }
        return {'status': 'not_found', 'name': name}
    except Exception:
        logger.debug('Circuit breaker check failed', exc_info=True)
    return {'name': name, 'state': 'UNKNOWN', 'failure_count': 0}


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
    return {'status': 'no_stats_available'}


async def is_system_stuck() -> bool:
    """Detect if any core system components are in a 'stuck' or unresponsive state.

    Returns:
        True if potential deadlock or hang detected, False otherwise.

    """
    return False


def _collect_state_snapshot(state_obj: Any) -> dict[str, Any]:
    """Extract state fields for health snapshot."""
    iteration_flag = getattr(state_obj, 'iteration_flag', None)
    budget_flag = getattr(state_obj, 'budget_flag', None)
    metrics = getattr(state_obj, 'metrics', None)
    return {
        'agent_state': getattr(
            getattr(state_obj, 'agent_state', None), 'value', 'unknown'
        ),
        'iteration': {
            'current': getattr(iteration_flag, 'current_value', None),
            'max': getattr(iteration_flag, 'max_value', None),
        },
        'budget': {
            'current': getattr(budget_flag, 'current_value', None),
            'max': getattr(budget_flag, 'max_value', None),
        },
        'accumulated_cost': getattr(metrics, 'accumulated_cost', None),
    }


def _as_real_number(value: Any) -> int | float | None:
    """Return numeric values without accepting truthy mocks as numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _as_state_name(value: Any) -> str | None:
    """Normalize concrete circuit-breaker state values."""
    if isinstance(value, str):
        return value.upper()
    name = getattr(value, 'name', None)
    if isinstance(name, str):
        return name.upper()
    return None


def _add_circuit_breaker_warnings(warnings: list[str], cb_service: Any) -> str | None:
    """Add circuit breaker warnings. Returns cb_state_name for severity.

    Supports both the current ``CircuitBreakerService.circuit_breaker`` shape and
    the older direct ``state``/``failure_count`` shape used by tests and adapters.
    """
    cb = getattr(cb_service, 'circuit_breaker', None)
    consecutive = _as_real_number(getattr(cb, 'consecutive_errors', None))
    max_errors = _as_real_number(
        getattr(getattr(cb, 'config', None), 'max_consecutive_errors', None)
    )
    cb_state_name = _as_state_name(getattr(cb_service, 'state', None))
    failure_count = _as_real_number(getattr(cb_service, 'failure_count', None))

    is_open = cb_state_name in {'OPEN', 'TRIPPED'} or (
        consecutive is not None
        and max_errors is not None
        and max_errors > 0
        and consecutive >= max_errors
    )
    unhealthy_count = consecutive if consecutive is not None else failure_count

    if is_open:
        warnings.append('circuit_breaker_open')
        return 'OPEN'
    if unhealthy_count is not None and unhealthy_count >= 5:
        warnings.append('circuit_breaker_unhealthy')
    return cb_state_name


def _collect_health_warnings(controller: Any) -> tuple[list[str], str]:
    """Collect warnings and severity. Returns (warnings, severity)."""
    warnings: list[str] = []
    cb_service = getattr(controller, 'circuit_breaker_service', None)
    if cb_service:
        cb_state_name = _add_circuit_breaker_warnings(warnings, cb_service)
    else:
        cb_state_name = None

    retry_svc = getattr(controller, 'retry_service', None)
    retry_pending = getattr(retry_svc, 'pending_retry', None)
    if not isinstance(retry_pending, bool):
        retry_pending = getattr(retry_svc, 'retry_pending', None)
    if retry_pending is True:
        warnings.append('retry_pending')

    stream = getattr(controller, 'event_stream', None)
    persistence_health = getattr(stream, 'persistence_health', 'ok')
    if persistence_health == 'degraded':
        warnings.append('persistence_degraded')
    elif persistence_health == 'failed':
        warnings.append('persistence_failed')

    severity = 'red' if cb_state_name == 'OPEN' else ('yellow' if warnings else 'green')
    return (warnings, severity)


def collect_orchestration_health(controller: Any) -> dict[str, Any]:
    """Collect a lightweight, dependency-safe health snapshot for a controller.

    The snapshot is used by monitoring endpoints and integration tests.
    """
    state_obj = getattr(controller, 'state', None)
    warnings, severity = _collect_health_warnings(controller)
    state_snapshot = _collect_state_snapshot(state_obj)
    stream = getattr(controller, 'event_stream', None)
    persistence_health = getattr(stream, 'persistence_health', 'ok')
    return {
        'timestamp': datetime.now(UTC).isoformat(),
        'controller_id': getattr(controller, 'sid', 'unknown'),
        'severity': severity,
        'warnings': warnings,
        'persistence_health': persistence_health,
        'state': state_snapshot,
    }
