"""Circuit breaker for autonomous agent safety.

Automatically pauses agent execution when anomalous behavior is detected:
- Consecutive errors
- Repeated high-risk actions
- Stuck detection triggers
- Budget consumption spikes
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.controller.state.state import State

from backend.core.logger import forge_logger as logger
from backend.events.action import ActionSecurityRisk
from backend.events.observation import ErrorObservation


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    enabled: bool = True
    max_consecutive_errors: int = (
        5  # Allow more consecutive errors to support exploratory or compilation retry loops
    )
    max_high_risk_actions: int = (
        5  # Reduced from 10 — 5 high-risk actions warrants intervention
    )
    max_stuck_detections: int = 8
    max_error_rate: float = 0.5  # 50% of last N actions
    error_rate_window: int = 10  # Look at last 10 actions

    # Adaptive scaling — when enabled, thresholds scale with task complexity
    # and iteration budget so that complex tasks get more breathing room.
    adaptive: bool = True

    def scaled(self, complexity: float, max_iterations: int) -> CircuitBreakerConfig:
        """Return a copy with thresholds scaled for the given task.

        Scale factors:
        - complexity 1-3  → 1×  (simple tasks keep defaults)
        - complexity 4-6  → 1.5×
        - complexity 7-10 → 2×

        For iteration budget, thresholds grow proportionally when the agent
        has a large runway (> 100 iterations).
        """
        if not self.adaptive:
            return self

        # Complexity multiplier (1.0 – 2.0)
        if complexity <= 3:
            c_mult = 1.0
        elif complexity <= 6:
            c_mult = 1.5
        else:
            c_mult = 2.0

        # Iteration budget multiplier (1.0 – 1.5)
        i_mult = min(1.0 + max(0, max_iterations - 100) / 400, 1.5)

        scale = c_mult * i_mult

        return CircuitBreakerConfig(
            enabled=self.enabled,
            max_consecutive_errors=max(
                self.max_consecutive_errors, int(self.max_consecutive_errors * scale)
            ),
            max_high_risk_actions=max(
                self.max_high_risk_actions, int(self.max_high_risk_actions * scale)
            ),
            max_stuck_detections=max(
                self.max_stuck_detections, int(self.max_stuck_detections * scale)
            ),
            max_error_rate=min(self.max_error_rate * (1 + (scale - 1) * 0.3), 0.8),
            error_rate_window=max(
                self.error_rate_window, int(self.error_rate_window * scale)
            ),
            adaptive=False,  # prevent re-scaling
        )


@dataclass
class CircuitBreakerResult:
    """Result of circuit breaker check."""

    tripped: bool
    reason: str
    action: str  # 'pause', 'stop', or 'switch_context'
    recommendation: str = ""
    system_message: str | None = None


class CircuitBreaker:
    """Monitors autonomous agent execution and triggers safety pauses.

    The circuit breaker trips when it detects:
    - Too many consecutive errors
    - Too many high-risk actions in short time
    - Repeated stuck detection warnings
    - Anomalous error rates

    When tripped, the agent is paused for human intervention.
    """

    def __init__(self, config: CircuitBreakerConfig) -> None:
        """Initialize circuit breaker.

        Args:
            config: Circuit breaker configuration

        """
        self.config = config
        self.consecutive_errors = 0
        self.high_risk_action_count = 0
        self.stuck_detection_count = 0
        self.recent_errors: deque[str] = deque(maxlen=config.error_rate_window * 2)
        self.recent_actions_success: deque[bool] = deque(
            maxlen=config.error_rate_window * 2
        )

        logger.info(
            "CircuitBreaker initialized: max_consecutive_errors=%s, "
            "max_high_risk_actions=%s (adaptive=%s)",
            config.max_consecutive_errors,
            config.max_high_risk_actions,
            config.adaptive,
        )

    def check(self, state: State | None = None) -> CircuitBreakerResult:
        """Check if circuit breaker should trip.

        Returns:
            CircuitBreakerResult indicating if breaker tripped

        """
        if not self.config.enabled:
            return CircuitBreakerResult(
                tripped=False,
                reason="Circuit breaker disabled",
                action="continue",
            )

        # Check various trip conditions

        # 1. Consecutive errors
        if self.consecutive_errors >= self.config.max_consecutive_errors:
            return CircuitBreakerResult(
                tripped=True,
                reason=f"Too many consecutive errors ({self.consecutive_errors})",
                action="pause",
                recommendation=(
                    f"The agent has encountered {self.consecutive_errors} consecutive errors. "
                    f"Please review the error logs and adjust the approach before continuing."
                ),
            )

        # 2. High-risk actions
        if self.high_risk_action_count >= self.config.max_high_risk_actions:
            return CircuitBreakerResult(
                tripped=True,
                reason=f"Too many high-risk actions ({self.high_risk_action_count})",
                action="pause",
                recommendation=(
                    f"The agent has attempted {self.high_risk_action_count} high-risk actions. "
                    f"Please review the actions and ensure the agent is behaving correctly."
                ),
            )

        # 3. Stuck detections
        # The step_guard_service already emits targeted recovery messages.
        # The circuit breaker only decides when to finally stop the agent.
        if self.stuck_detection_count >= self.config.max_stuck_detections:
            return CircuitBreakerResult(
                tripped=True,
                reason=f"Too many stuck loop detections ({self.stuck_detection_count})",
                action="stop",
                recommendation=(
                    f"The agent has been detected stuck in loops {self.stuck_detection_count} times. "
                    f"Stopping to prevent further wasted computation."
                ),
            )

        # 4. Error rate too high
        error_rate = self._calculate_error_rate()
        if (
            error_rate > self.config.max_error_rate
            and len(self.recent_actions_success) >= self.config.error_rate_window
        ):
            return CircuitBreakerResult(
                tripped=True,
                reason=f"Error rate too high ({error_rate:.1%} in last {len(self.recent_actions_success)} actions)",
                action="pause",
                recommendation=(
                    f"The agent has a {error_rate:.1%} error rate in recent actions. "
                    f"Please review the strategy and errors before continuing."
                ),
            )

        # No trip conditions met
        return CircuitBreakerResult(
            tripped=False,
            reason="All checks passed",
            action="continue",
        )

    def record_error(self, error: Exception) -> None:
        """Record an error occurrence.

        Args:
            error: The exception that occurred

        """
        self.consecutive_errors += 1
        self.recent_errors.append(str(error))
        self.recent_actions_success.append(False)

    def record_success(self) -> None:
        """Record a successful action."""
        self.consecutive_errors = 0  # Reset consecutive error counter
        self.recent_actions_success.append(True)

    def record_high_risk_action(self, risk_level: ActionSecurityRisk) -> None:
        """Record a high-risk action.

        Args:
            risk_level: Risk level of the action

        """
        if risk_level == ActionSecurityRisk.HIGH:
            self.high_risk_action_count += 1

    def record_stuck_detection(self) -> None:
        """Record a stuck loop detection."""
        self.stuck_detection_count += 1
        logger.warning("Stuck detection #%s recorded", self.stuck_detection_count)

    def record_progress_signal(self, note: str) -> None:
        """Proactively decrement the stuck loop detection count when LLM signals progress."""
        old_count = self.stuck_detection_count
        self.stuck_detection_count = max(0, self.stuck_detection_count - 2)
        logger.info(
            "Progress signal received: %r. Reduced stuck_detection_count from %d to %d.",
            note,
            old_count,
            self.stuck_detection_count,
        )

    def adapt(self, complexity: float, max_iterations: int) -> None:
        """Adapt thresholds to task complexity and iteration budget.

        Should be called once after the first user message is analysed.
        """
        new_config = self.config.scaled(complexity, max_iterations)
        if new_config is not self.config:
            logger.info(
                "CircuitBreaker adapted: max_errors %s→%s, max_risk %s→%s, "
                "error_rate %.0f%%→%.0f%%, window %s→%s",
                self.config.max_consecutive_errors,
                new_config.max_consecutive_errors,
                self.config.max_high_risk_actions,
                new_config.max_high_risk_actions,
                self.config.max_error_rate * 100,
                new_config.max_error_rate * 100,
                self.config.error_rate_window,
                new_config.error_rate_window,
            )
            self.config = new_config

    def reset(self) -> None:
        """Reset circuit breaker state."""
        self.consecutive_errors = 0
        self.high_risk_action_count = 0
        self.stuck_detection_count = 0
        self.recent_errors.clear()
        self.recent_actions_success.clear()
        logger.info("Circuit breaker reset")

    def _update_metrics(self, state: State) -> None:
        """Update metrics from state.

        Args:
            state: Current agent state

        """
        # Look at recent history to update metrics
        recent_history = state.history[-20:]

        error_count = sum(
            1 for event in recent_history if isinstance(event, ErrorObservation)
        )

        # Update error tracking
        if error_count > len(self.recent_errors):
            # New errors detected
            self.consecutive_errors += error_count - len(self.recent_errors)

    def _calculate_error_rate(self) -> float:
        """Calculate error rate over recent actions.

        Returns:
            Error rate as a float (0.0 to 1.0)

        """
        if not self.recent_actions_success:
            return 0.0

        # deque does not support slicing; materialise the tail via list()
        recent_window = list(self.recent_actions_success)[
            -self.config.error_rate_window :
        ]
        errors = sum(1 for success in recent_window if not success)

        return errors / len(recent_window) if recent_window else 0.0
