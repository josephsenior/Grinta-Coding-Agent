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
    DEFAULT_NO_STEP_PROGRESS_TIMEOUT_SECONDS,
    DEFAULT_STUCK_AUTO_RECOVER_COOLDOWN_SECONDS,
    DEFAULT_TEXT_EDITOR_SYNTAX_PAUSE,
    DEFAULT_TEXT_EDITOR_SYNTAX_SWITCH,
)
from backend.core.logger import app_logger as logger
from backend.ledger.action import ActionSecurityRisk
from backend.ledger.observation import ErrorObservation

# Per-tool keys for file edit failures. Syntax validation rejects are
# tracked separately with higher trip thresholds than match/path/guard errors.
FILE_EDIT_BUCKET = 'file_edit'
FILE_EDIT_SYNTAX_BUCKET = 'file_edit_syntax'

_PER_TOOL_ERRORS_MAX = 100


def classify_file_edit_error_bucket(content: str) -> str:
    """Map file-edit error text to a circuit-breaker per-tool bucket.

    Syntax validation failures are common while iterating on generated code;
    they use ``FILE_EDIT_SYNTAX_BUCKET`` and higher ``check()``
    thresholds than deterministic match failures.
    """
    if 'syntax validation failed' in (content or '').lower():
        return FILE_EDIT_SYNTAX_BUCKET
    return FILE_EDIT_BUCKET


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

    # No-step-progress watchdog.  If state==RUNNING for at least this many
    # seconds with no recorded ``step()`` call, the watchdog fires.  Set
    # ``<= 0`` to disable the watchdog entirely.
    no_step_progress_timeout_seconds: float = (
        DEFAULT_NO_STEP_PROGRESS_TIMEOUT_SECONDS
    )
    # Cooldown between auto-recovery attempts.  After the watchdog issues
    # one ``schedule_step_soon`` to recover, it waits this long before
    # declaring a second stall fatal.
    auto_recover_cooldown_seconds: float = (
        DEFAULT_STUCK_AUTO_RECOVER_COOLDOWN_SECONDS
    )

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
        # failures (e.g. file edits + npm lint) from compounding into
        # a single global counter that trips too early.
        self._per_tool_errors: dict[str, int] = {}

        # No-step-progress watchdog state.  The watchdog fires when the
        # controller stays in AgentState.RUNNING for too long without
        # anyone calling step()/schedule_step_soon().  This catches the
        # ``_step_pending``-clearing race that previously left the agent
        # silently polling forever.
        self._last_step_call_ts: float | None = None
        self._auto_recover_attempts: int = 0
        self._last_auto_recover_ts: float | None = None

        logger.info(
            'CircuitBreaker initialized: max_consecutive_errors=%s, '
            'max_high_risk_actions=%s (adaptive=%s) '
            'no_step_progress_timeout=%.0fs auto_recover_cooldown=%.0fs',
            config.max_consecutive_errors,
            config.max_high_risk_actions,
            config.adaptive,
            config.no_step_progress_timeout_seconds,
            config.auto_recover_cooldown_seconds,
        )

    def _trip_if_file_edit_syntax(
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
                f'Repeated file edit syntax validation failures ({str_replace_syntax})'
            ),
            action='pause'
            if str_replace_syntax >= DEFAULT_TEXT_EDITOR_SYNTAX_PAUSE
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

        # 2.5 File-edit syntax failures. Match/path/stale-context errors are
        # returned directly by the edit tools; adding a second circuit-breaker
        # warning here caused noisy false positives during multi-edit retries.
        str_replace_syntax = self.get_tool_error_count(FILE_EDIT_SYNTAX_BUCKET)

        # Syntax rejects: much higher budget than match-not-found / path /
        # guard failures. Since the default write path now downgrades the
        # strict veto to a *post-write warning* (see
        # ``FileEditor._maybe_validate_syntax_for_file``), the only way this
        # bucket fills up is if a caller explicitly set
        # ``GRINTA_STRICT_WRITE_VALIDATION=1``. We therefore pick thresholds
        # that are generous enough to let the agent iterate on a genuinely
        # hard file rather than trigger a pause on minor churn.
        if trip := self._trip_if_file_edit_syntax(str_replace_syntax):
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

    def get_tool_error_count(self, tool_name: str) -> int:
        """Return the current error count for a given tool bucket."""
        return self._per_tool_errors.get(tool_name, 0)

    def record_high_risk_action(self, security_risk: ActionSecurityRisk) -> None:
        """Record a high-risk action attempt."""
        if security_risk == ActionSecurityRisk.HIGH:
            self.high_risk_action_count += 1

    def record_stuck_detection(self) -> None:
        """Record a stuck loop detection event."""
        self.stuck_detection_count += 1

    def record_step_call(self, ts: float | None = None) -> None:
        """Mark that ``step()`` (or ``schedule_step_soon()``) was just invoked.

        The no-step-progress watchdog uses this timestamp to detect the
        ``_step_pending``-clearing race: if state is RUNNING but no step
        request has been recorded for too long, something dropped the
        re-trigger and we need to (auto-)recover.

        Call this from:
        - ``SessionOrchestrator.step()`` (direct entry)
        - ``SessionOrchestrator.schedule_step_soon()`` (deferred entry)
        """
        import time as _time

        self._last_step_call_ts = (
            ts if ts is not None else _time.monotonic()
        )
        # Any new step call resets the auto-recover counter so a successful
        # sequence of steps that happens to be slow doesn't get penalised
        # by stale state from a previous stall.
        if self._auto_recover_attempts > 0:
            self._auto_recover_attempts = 0
            self._last_auto_recover_ts = None

    def check_no_step_progress(
        self,
        agent_state: 'AgentState | None' = None,
        now: float | None = None,
    ) -> CircuitBreakerResult | None:
        """Watchdog: detect RUNNING state with no recent step() call.

        Returns:
            - ``None`` if everything is healthy (state != RUNNING, or a
              step call was recorded within the configured timeout).
            - ``CircuitBreakerResult(action='auto_recover_once')`` on the
              first stall in a cooldown window.  The caller is expected to
              invoke ``controller.schedule_step_soon()`` as the recovery.
            - ``CircuitBreakerResult(action='stop', tripped=True)`` when a
              second stall occurs within ``auto_recover_cooldown_seconds``,
              indicating a persistent race that auto-recovery can't fix.
        """
        if not self.config.enabled:
            return None

        timeout = self.config.no_step_progress_timeout_seconds
        if timeout <= 0:
            return None  # watchdog disabled

        # Only meaningful while the agent is supposed to be running.
        # Note: AgentState.RUNNING.value is 'running' (lowercase), so we use
        # .name == 'RUNNING' to match the enum member name.
        if agent_state is None:
            agent_state = getattr(self, '_cached_state', None)
        if agent_state is None:
            return None
        if not (hasattr(agent_state, 'name') and agent_state.name == 'RUNNING'):
            return None

        if self._last_step_call_ts is None:
            return None  # never had a step call — nothing to compare to

        import time as _time

        current = now if now is not None else _time.monotonic()
        elapsed = current - self._last_step_call_ts
        if elapsed < timeout:
            return None

        # First stall inside the cooldown window → auto-recover once.
        cooldown = self.config.auto_recover_cooldown_seconds
        if (
            self._last_auto_recover_ts is None
            or (current - self._last_auto_recover_ts) > cooldown
        ):
            self._auto_recover_attempts += 1
            self._last_auto_recover_ts = current
            logger.warning(
                'No-step-progress watchdog: no step() call for %.1fs in RUNNING; '
                'issuing auto-recover (attempt %d, cooldown=%.0fs)',
                elapsed,
                self._auto_recover_attempts,
                cooldown,
            )
            return CircuitBreakerResult(
                tripped=False,
                reason=(
                    f'No step() call recorded for {elapsed:.1f}s while in '
                    f'RUNNING; auto-recover attempt {self._auto_recover_attempts}'
                ),
                action='auto_recover_once',
                recommendation=(
                    'The agent loop appears stalled in RUNNING state with no '
                    'scheduled step.  Issuing one schedule_step_soon() to '
                    'recover.'
                ),
            )

        # Second stall within the cooldown window → fatal.
        logger.error(
            'No-step-progress watchdog: auto-recover did not help after %.1fs; '
            'forcing ERROR state to break the stall loop',
            elapsed,
        )
        return CircuitBreakerResult(
            tripped=True,
            reason=(
                f'Agent stuck in RUNNING with no step progress for '
                f'{elapsed:.1f}s after auto-recover attempt'
            ),
            action='stop',
            recommendation=(
                'The agent loop is stuck in RUNNING state.  This usually '
                'indicates the _step_pending race documented in '
                'schedule_step_soon().  Stopping the agent to surface the '
                'issue to the user.'
            ),
        )

    def update_cached_state(self, agent_state: 'AgentState | None') -> None:
        """Cache the latest AgentState so the watchdog can read it lazily."""
        self._cached_state = agent_state

    def record_progress_signal(self, note: str = '') -> None:
        """Reduce stuck-detection pressure when a progress observation is received.

        This is the sole mechanism for reducing ``stuck_detection_count``.
        ``record_success`` handles only error-counter and per-tool decay;
        it does **not** touch stuck detection. Only observation types listed
        in ``_PROGRESS_OBSERVATION_TYPES`` (file edits, task tracking
        updates, agent delegation, lsp queries) trigger this call.
        """
        decay = max(0, getattr(self.config, 'error_decay_per_success', 0))
        if decay <= 0:
            self.stuck_detection_count = 0
        else:
            self.stuck_detection_count = max(0, self.stuck_detection_count - decay)
        logger.info(
            'Progress signal received from %s. stuck_detection_count reduced to %d.',
            note,
            self.stuck_detection_count,
        )

    def record_error(self, error: Exception, tool_name: str = '') -> None:
        """Record an error occurrence.

        Args:
            error: The exception that occurred
            tool_name: Optional tool name for per-tool tracking

        """
        if tool_name != FILE_EDIT_SYNTAX_BUCKET:
            self.consecutive_errors += 1
        self.recent_errors.append(str(error))
        self.recent_actions_success.append(False)
        if tool_name:
            self._per_tool_errors[tool_name] = (
                self._per_tool_errors.get(tool_name, 0) + 1
            )
            if len(self._per_tool_errors) > _PER_TOOL_ERRORS_MAX:
                stale_keys = sorted(
                    self._per_tool_errors, key=lambda k: self._per_tool_errors[k]
                )[: len(self._per_tool_errors) - _PER_TOOL_ERRORS_MAX]
                for key in stale_keys:
                    del self._per_tool_errors[key]

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
        if tool_name:
            if tool_name == FILE_EDIT_BUCKET:
                self._per_tool_errors.pop(FILE_EDIT_SYNTAX_BUCKET, None)
            old_count = self._per_tool_errors.get(tool_name, 0)
            if decay <= 0:
                self._per_tool_errors[tool_name] = 0
            else:
                new_count = max(0, old_count - decay)
                if new_count <= 0:
                    self._per_tool_errors.pop(tool_name, None)
                else:
                    self._per_tool_errors[tool_name] = new_count

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
        # No-step-progress watchdog state.  Reset on full breaker reset so a
        # new session starts with a clean slate (and so a recovered stall
        # doesn't carry over into the next user message).
        self._last_step_call_ts = None
        self._auto_recover_attempts = 0
        self._last_auto_recover_ts = None
        logger.info('Circuit breaker reset')

    def reset_task_counters(self) -> None:
        """Reset cumulative task-scoped counters that should not persist across tasks.

        Called when the agent receives a new user message indicating a task
        switch. This prevents false-positive breaker trips caused by
        accumulated ``stuck_detection_count`` or ``high_risk_action_count``
        from previous tasks.

        Unlike :meth:`reset`, this preserves ``recent_errors`` and
        ``recent_actions_success`` so that the error-rate sliding window
        continues to provide signal across task boundaries.
        """
        self.consecutive_errors = 0
        self.stuck_detection_count = 0
        self.high_risk_action_count = 0
        self._per_tool_errors.clear()
        logger.debug(
            'Circuit breaker task counters reset '
            '(consecutive_errors=0, stuck=0, high_risk=0, per_tool cleared)'
        )

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
