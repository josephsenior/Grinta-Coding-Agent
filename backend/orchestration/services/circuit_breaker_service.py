from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.constants import (
    DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS,
    DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS,
    DEFAULT_AGENT_MAX_STUCK_DETECTIONS,
)
from backend.core.logger import app_logger as logger
from backend.orchestration.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerResult,
)

if TYPE_CHECKING:
    from backend.core.config.agent_config import AgentConfig
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.session_orchestrator import SessionOrchestrator


class CircuitBreakerService:
    """Encapsulates circuit breaker configuration and interactions."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context
        self._circuit_breaker: CircuitBreaker | None = None

    @property
    def controller(self) -> SessionOrchestrator:
        return self._context.get_controller()

    # ------------------------------------------------------------------ #
    # Setup / configuration
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """Disable circuit breaker handling."""
        self._circuit_breaker = None
        setattr(self.controller, 'circuit_breaker', None)

    def configure(self, agent_config: AgentConfig) -> None:
        """Configure the circuit breaker based on agent configuration."""
        self.reset()

        if not getattr(agent_config, 'enable_circuit_breaker', True):
            return

        config_kwargs: dict[str, Any] = {
            'enabled': True,
            'max_consecutive_errors': getattr(
                agent_config,
                'max_consecutive_errors',
                DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS,
            ),
            'max_high_risk_actions': getattr(
                agent_config,
                'max_high_risk_actions',
                DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS,
            ),
            'max_stuck_detections': getattr(
                agent_config,
                'max_stuck_detections',
                DEFAULT_AGENT_MAX_STUCK_DETECTIONS,
            ),
        }

        max_error_rate = getattr(agent_config, 'max_error_rate', None)
        if isinstance(max_error_rate, int | float):
            config_kwargs['max_error_rate'] = float(max_error_rate)

        error_rate_window = getattr(agent_config, 'error_rate_window', None)
        if isinstance(error_rate_window, int):
            config_kwargs['error_rate_window'] = error_rate_window

        cb_config = CircuitBreakerConfig(**config_kwargs)

        self._circuit_breaker = CircuitBreaker(cb_config)
        setattr(self.controller, 'circuit_breaker', self._circuit_breaker)
        logger.info('Circuit breaker enabled for anomaly detection')

    # ------------------------------------------------------------------ #
    # Circuit breaker interactions
    # ------------------------------------------------------------------ #
    @property
    def circuit_breaker(self) -> CircuitBreaker | None:
        """Return the configured circuit breaker instance, if any."""
        return self._circuit_breaker

    def check(self) -> CircuitBreakerResult | None:
        """Run circuit breaker check for current controller state."""
        if not self._circuit_breaker:
            return None
        return self._circuit_breaker.check(getattr(self.controller, 'state', None))

    def record_error(self, error: Exception, tool_name: str = '') -> None:
        """Record an error with the circuit breaker."""
        if self._circuit_breaker:
            self._circuit_breaker.record_error(error, tool_name=tool_name)

    def record_success(self, tool_name: str = '') -> None:
        """Record successful execution."""
        if self._circuit_breaker:
            self._circuit_breaker.record_success(tool_name=tool_name)

    def record_high_risk_action(self, security_risk) -> None:
        """Record a high-risk action."""
        if self._circuit_breaker and security_risk is not None:
            self._circuit_breaker.record_high_risk_action(security_risk)

    def record_stuck_detection(self) -> None:
        """Record a stuck detection event."""
        if self._circuit_breaker:
            self._circuit_breaker.record_stuck_detection()

    def record_progress_signal(self, note: str = '') -> None:
        """Record a progress signal that reduces stuck-detection pressure."""
        if self._circuit_breaker:
            self._circuit_breaker.record_progress_signal(note)

    def adapt(self, complexity: float, max_iterations: int) -> None:
        """Adapt thresholds to task complexity and iteration budget."""
        if self._circuit_breaker:
            self._circuit_breaker.adapt(complexity, max_iterations)

    def reset_for_new_turn(self) -> None:
        """Reset per-turn counters when a new user message arrives.

        A new user message is an implicit acknowledgment of any previous
        circuit breaker trip. Carrying stale counters into the next turn
        would immediately re-trip on the very first step of the new turn,
        causing the warning to re-render without any new high-risk action
        being taken.
        """
        if self._circuit_breaker is not None:
            self._circuit_breaker.reset()
