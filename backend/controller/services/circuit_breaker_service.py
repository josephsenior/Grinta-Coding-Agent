from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerResult,
)
from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.services.controller_context import ControllerContext
    from backend.core.config.agent_config import AgentConfig


class CircuitBreakerService:
    """Encapsulates circuit breaker configuration and interactions."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context
        self._circuit_breaker: CircuitBreaker | None = None

    @property
    def controller(self) -> AgentController:
        return self._context.get_controller()

    # ------------------------------------------------------------------ #
    # Setup / configuration
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """Disable circuit breaker handling."""
        self._circuit_breaker = None
        setattr(self.controller, "circuit_breaker", None)

    def configure(self, agent_config: AgentConfig) -> None:
        """Configure the circuit breaker based on agent configuration."""
        self.reset()

        if not getattr(agent_config, "enable_circuit_breaker", True):
            return

        config_kwargs = {
            "enabled": True,
            "max_consecutive_errors": getattr(agent_config, "max_consecutive_errors", 5),
            "max_high_risk_actions": getattr(agent_config, "max_high_risk_actions", 10),
            "max_stuck_detections": getattr(agent_config, "max_stuck_detections", 3),
        }

        max_error_rate = getattr(agent_config, "max_error_rate", None)
        if isinstance(max_error_rate, int | float):
            config_kwargs["max_error_rate"] = float(max_error_rate)

        error_rate_window = getattr(agent_config, "error_rate_window", None)
        if isinstance(error_rate_window, int):
            config_kwargs["error_rate_window"] = error_rate_window

        cb_config = CircuitBreakerConfig(**config_kwargs)

        self._circuit_breaker = CircuitBreaker(cb_config)
        setattr(self.controller, "circuit_breaker", self._circuit_breaker)
        logger.info("CircuitBreaker enabled for anomaly detection")

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
        return self._circuit_breaker.check(self.controller.state)

    def record_error(self, error: Exception) -> None:
        """Record an error with the circuit breaker."""
        if self._circuit_breaker:
            self._circuit_breaker.record_error(error)

    def record_success(self) -> None:
        """Record successful execution."""
        if self._circuit_breaker:
            self._circuit_breaker.record_success()

    def record_high_risk_action(self, security_risk) -> None:
        """Record a high-risk action."""
        if self._circuit_breaker and security_risk is not None:
            self._circuit_breaker.record_high_risk_action(security_risk)

    def record_stuck_detection(self) -> None:
        """Record a stuck detection event."""
        if self._circuit_breaker:
            self._circuit_breaker.record_stuck_detection()

    def adapt(self, complexity: float, max_iterations: int) -> None:
        """Adapt thresholds to task complexity and iteration budget."""
        if self._circuit_breaker:
            self._circuit_breaker.adapt(complexity, max_iterations)
