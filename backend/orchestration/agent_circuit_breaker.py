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
    from backend.orchestration.state.state import State

from backend.core.constants import (
    DEFAULT_AGENT_ERROR_DECAY_PER_SUCCESS,
    DEFAULT_AGENT_ERROR_RATE_WINDOW,
    DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS,
    DEFAULT_AGENT_MAX_ERROR_RATE,
    DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS,
    DEFAULT_AGENT_MAX_STUCK_DETECTIONS,
    DEFAULT_STUCK_PROGRESS_SIGNAL_DECREMENT,
    DEFAULT_TEXT_EDITOR_HARD_PAUSE,
    DEFAULT_TEXT_EDITOR_HARD_SWITCH,
    DEFAULT_TEXT_EDITOR_SYNTAX_PAUSE,
    DEFAULT_TEXT_EDITOR_SYNTAX_SWITCH,
)
from backend.core.logger import app_logger as logger
from backend.ledger.action import ActionSecurityRisk
from backend.ledger.observation import ErrorObservation

# Per-tool keys for text_editor failures. Syntax validation rejects are
# tracked separately with higher trip thresholds than match/path/guard errors.
TEXT_EDITOR_TOOL_NAME = 'text_editor'
TEXT_EDITOR_SYNTAX_TOOL_NAME = 'text_editor_syntax'


def classify_text_editor_error_bucket(content: str) -> str:
    """Map text_editor error text to a circuit-breaker per-tool bucket.

    Syntax validation failures are common while iterating on generated code;
    they use ``TEXT_EDITOR_SYNTAX_TOOL_NAME`` and higher ``check()``
    thresholds than deterministic match failures.
    """
    if 'syntax validation failed' in (content or '').lower():
        return TEXT_EDITOR_SYNTAX_TOOL_NAME
    return TEXT_EDITOR_TOOL_NAME


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    enabled: bool = True
    max_consecutive_errors: int = DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS
    max_high_risk_actions: int = DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS
    max_stuck_detections: int = DEFAULT_AGENT_MAX_STUCK_DETECTIONS
    max_error_rate: float = DEFAULT_AGENT_MAX_ERROR_RATE
    error_rate_window: int = DEFAULT_AGENT_ERROR_RATE_WINDOW

    # Hysteresis: how much one success decays the error counters. The
    # historic behaviour was a hard zero-reset, which let one housekeeping
    # success mask a still-failing tool. Default is now ``1`` (decay one
    # step per success). Set ``0`` to restore the legacy zero-reset.
    error_decay_per_success: int = DEFAULT_AGENT_ERROR_DECAY_PER_SUCCESS

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
            error_decay_per_success=self.error_decay_per_success,
            adaptive=False,  # prevent re-scaling
        )


@dataclass
class CircuitBreakerResult:
    """Result of circuit breaker check."""

    tripped: bool
    reason: str
    action: str  # 'pause', 'stop', or 'switch_context'
    recommendation: str = ''
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
        # Per-tool-type consecutive error tracking — prevents cross-task
        # failures (e.g. symbol_editor + npm lint) from compounding into
        # a single global counter that trips too early.
        self._per_tool_errors: dict[str, int] = {}

        logger.info(
            'CircuitBreaker initialized: max_consecutive_errors=%s, '
            'max_high_risk_actions=%s (adaptive=%s)',
            config.max_consecutive_errors,
            config.max_high_risk_actions,
            config.adaptive,
        )

    def _trip_if_text_editor_syntax(
        self, str_replace_syntax: int
    ) -> CircuitBreakerResult | None:
        if str_replace_syntax < DEFAULT_TEXT_EDITOR_SYNTAX_SWITCH:
            return None
        recommendation = (
            'Repeated syntax validation failures on edited files. '
            'Prefer minimal parsing-safe stubs and smaller surgical edits; '
            'refresh file context with read_file before reattempting.'
        )
        if str_replace_syntax >= DEFAULT_TEXT_EDITOR_SYNTAX_PAUSE:
            recommendation = (
                recommendation
                + ' Syntax-validation retries are now blocked until strategy changes.'
            )
        return CircuitBreakerResult(
            tripped=True,
            reason=(
                'Repeated text_editor syntax validation failures '
                f'({str_replace_syntax})'
            ),
            action='pause'
            if str_replace_syntax >= DEFAULT_TEXT_EDITOR_SYNTAX_PAUSE
            else 'switch_context',
            recommendation=recommendation,
            system_message=recommendation,
        )

    def _trip_if_text_editor_hard(
        self, str_replace_hard: int
    ) -> CircuitBreakerResult | None:
        if str_replace_hard < DEFAULT_TEXT_EDITOR_HARD_SWITCH:
            return None
        recommendation = (
            'Repeated deterministic text_editor failures detected. '
            'Refresh file context with read_file before reattempting. '
            'If this persists, switch to a different edit strategy.'
        )
        if str_replace_hard >= DEFAULT_TEXT_EDITOR_HARD_PAUSE:
            recommendation = (
                recommendation
                + ' text_editor retries are now blocked until strategy changes.'
            )
        return CircuitBreakerResult(
            tripped=True,
            reason=(
                'Repeated text_editor deterministic failures '
                f'({str_replace_hard})'
            ),
            action='pause'
            if str_replace_hard >= DEFAULT_TEXT_EDITOR_HARD_PAUSE
            else 'switch_context',
            recommendation=recommendation,
            system_message=recommendation,
        )

    def check(self, state: State | None = None) -> CircuitBreakerResult:
        """Check if circuit breaker should trip.

        Returns:
            CircuitBreakerResult indicating if breaker tripped

        """
        if not self.config.enabled:
            return CircuitBreakerResult(
                tripped=False,
                reason='Circuit breaker disabled',
                action='continue',
            )

        # Check various trip conditions

        # 1. Consecutive errors
        if self.consecutive_errors >= self.config.max_consecutive_errors:
            return CircuitBreakerResult(
                tripped=True,
                reason=f'Too many consecutive errors ({self.consecutive_errors})',
                action='pause',
                recommendation=(
                    f'The agent has encountered {self.consecutive_errors} consecutive errors. '
                    f'Please review the error logs and adjust the approach before continuing.'
                ),
            )

        # 2. High-risk actions
        if self.high_risk_action_count >= self.config.max_high_risk_actions:
            return CircuitBreakerResult(
                tripped=True,
                reason=f'Too many high-risk actions ({self.high_risk_action_count})',
                action='pause',
                recommendation=(
                    f'The agent has attempted {self.high_risk_action_count} high-risk actions. '
                    f'Please review the actions and ensure the agent is behaving correctly.'
                ),
            )

        # 2.5 Deterministic same-tool failures (text_editor taxonomy)
        str_replace_hard = self.get_tool_error_count(TEXT_EDITOR_TOOL_NAME)
        str_replace_syntax = self.get_tool_error_count(
            TEXT_EDITOR_SYNTAX_TOOL_NAME
        )

        # Syntax rejects: much higher budget than match-not-found / path /
        # guard failures. Since the default write path now downgrades the
        # strict veto to a *post-write warning* (see
        # ``FileEditor._maybe_validate_syntax_for_file``), the only way this
        # bucket fills up is if a caller explicitly set
        # ``GRINTA_STRICT_WRITE_VALIDATION=1``. We therefore pick thresholds
        # that are generous enough to let the agent iterate on a genuinely
        # hard file rather than trigger a pause on minor churn.
        if trip := self._trip_if_text_editor_syntax(str_replace_syntax):
            return trip

        if trip := self._trip_if_text_editor_hard(str_replace_hard):
            return trip

        # 3. Stuck detections
        # The step_guard_service already emits targeted recovery messages.
        # The circuit breaker only decides when to finally stop the agent.
        if self.stuck_detection_count >= self.config.max_stuck_detections:
            return CircuitBreakerResult(
                tripped=True,
                reason=f'Too many stuck loop detections ({self.stuck_detection_count})',
                action='stop',
                recommendation=(
                    f'The agent has been detected stuck in loops {self.stuck_detection_count} times. '
                    f'Stopping to prevent further wasted computation.'
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
                reason=f'Error rate too high ({error_rate:.1%} in last {len(self.recent_actions_success)} actions)',
                action='pause',
                recommendation=(
                    f'The agent has a {error_rate:.1%} error rate in recent actions. '
                    f'Please review the strategy and errors before continuing.'
                ),
            )

        # No trip conditions met
        return CircuitBreakerResult(
            tripped=False,
            reason='All checks passed',
            action='continue',
        )

    def record_error(self, error: Exception, tool_name: str = '') -> None:
        """Record an error occurrence.

        Args:
            error: The exception that occurred
            tool_name: Optional tool name for per-tool tracking

        """
        # Syntax validation failures are higher-variance; do not consume the
        # global consecutive-error budget (else they trip before the syntax bucket).
        if tool_name != TEXT_EDITOR_SYNTAX_TOOL_NAME:
            self.consecutive_errors += 1
        self.recent_errors.append(str(error))
        self.recent_actions_success.append(False)
        if tool_name:
            self._per_tool_errors[tool_name] = (
                self._per_tool_errors.get(tool_name, 0) + 1
            )

    def record_success(self, tool_name: str = '') -> None:
        """Record a successful action.

        With hysteresis (``error_decay_per_success > 0``), the global
        ``consecutive_errors`` counter and the per-tool counters are
        decayed by that amount instead of being zeroed. This prevents a
        single housekeeping success from masking a still-failing tool.
        Set ``error_decay_per_success = 0`` in the config to restore the
        legacy zero-reset behaviour.
        """
        decay = max(0, getattr(self.config, 'error_decay_per_success', 0))
        if decay <= 0:
            self.consecutive_errors = 0
        else:
            self.consecutive_errors = max(0, self.consecutive_errors - decay)
        self.recent_actions_success.append(True)
        if tool_name in (
            TEXT_EDITOR_TOOL_NAME,
            TEXT_EDITOR_SYNTAX_TOOL_NAME,
        ):
            if decay <= 0:
                self._per_tool_errors.pop(TEXT_EDITOR_TOOL_NAME, None)
                self._per_tool_errors.pop(TEXT_EDITOR_SYNTAX_TOOL_NAME, None)
            else:
                for key in (TEXT_EDITOR_TOOL_NAME, TEXT_EDITOR_SYNTAX_TOOL_NAME):
                    cur = self._per_tool_errors.get(key, 0)
                    if cur <= decay:
                        self._per_tool_errors.pop(key, None)
                    else:
                        self._per_tool_errors[key] = cur - decay
        elif tool_name:
            if decay <= 0:
                self._per_tool_errors.pop(tool_name, None)
            else:
                cur = self._per_tool_errors.get(tool_name, 0)
                if cur <= decay:
                    self._per_tool_errors.pop(tool_name, None)
                else:
                    self._per_tool_errors[tool_name] = cur - decay

    def get_tool_error_count(self, tool_name: str) -> int:
        """Return consecutive error count for a specific tool type."""
        return self._per_tool_errors.get(tool_name, 0)

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
        logger.warning('Stuck detection #%s recorded', self.stuck_detection_count)

    def record_progress_signal(self, note: str) -> None:
        """Proactively decrement the stuck loop detection count when LLM signals progress."""
        old_count = self.stuck_detection_count
        self.stuck_detection_count = max(
            0, self.stuck_detection_count - DEFAULT_STUCK_PROGRESS_SIGNAL_DECREMENT
        )
        logger.info(
            'Progress signal received: %r. Reduced stuck_detection_count from %d to %d.',
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
                'CircuitBreaker adapted: max_errors %s→%s, max_risk %s→%s, '
                'error_rate %.0f%%→%.0f%%, window %s→%s',
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
        self._per_tool_errors.clear()
        logger.info('Circuit breaker reset')

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
