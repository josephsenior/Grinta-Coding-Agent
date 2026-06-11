"""Tests for the no-step-progress watchdog in CircuitBreaker."""

import pytest

from backend.core.schemas import AgentState
from backend.orchestration.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)


class TestNoStepProgressWatchdog:
    """Verify the no-step-progress watchdog detects and recovers from stalls."""

    @pytest.fixture
    def cb(self):
        """Create a circuit breaker with a very short timeout for fast tests."""
        config = CircuitBreakerConfig(
            enabled=True,
            no_step_progress_timeout_seconds=0.1,  # 100ms
            auto_recover_cooldown_seconds=0.15,  # 150ms
        )
        return CircuitBreaker(config)

    def test_watchdog_quiet_when_steps_happen(self, cb):
        """No result if step calls are recorded within the timeout."""
        now = 10.0
        cb.record_step_call(ts=now - 0.01)  # 10ms ago — well within 100ms

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=now)

        assert result is None, 'Watchdog should be silent when step was called recently'

    def test_watchdog_fires_after_timeout(self, cb):
        """First stall within the timeout fires auto_recover_once."""
        now = 10.0
        cb.record_step_call(ts=now - 0.5)  # 500ms ago — past 100ms timeout

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=now)

        assert result is not None
        assert result.action == 'auto_recover_once'
        assert result.tripped is False
        assert cb._auto_recover_attempts == 1
        assert cb._last_auto_recover_ts == now

    def test_watchdog_second_stall_within_cooldown_is_fatal(self, cb):
        """Second stall inside the cooldown window forces ERROR (action=stop)."""
        now = 10.0

        # First stall — auto_recover_once
        cb.record_step_call(ts=now - 0.5)
        cb._auto_recover_attempts = 1
        cb._last_auto_recover_ts = now - 0.01  # 10ms ago — within cooldown

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=now)

        assert result is not None
        assert result.action == 'stop'
        assert result.tripped is True

    def test_watchdog_resets_after_successful_recover(self, cb):
        """If a step call arrives after auto_recover, counter resets."""
        now = 10.0

        # Simulate a stall that auto-recovered
        cb.record_step_call(ts=now - 0.5)
        cb._auto_recover_attempts = 1
        cb._last_auto_recover_ts = now - 0.01

        # Now a new step call arrives (the auto-recovery worked)
        cb.record_step_call(ts=now)

        # Verify counter was reset
        assert cb._auto_recover_attempts == 0
        assert cb._last_auto_recover_ts is None

        # And watchdog is now silent
        result = cb.check_no_step_progress(
            agent_state=AgentState.RUNNING, now=now + 0.05
        )
        assert result is None

    def test_watchdog_ignores_non_running_state(self, cb):
        """Watchdog does not fire when state is not RUNNING."""
        now = 10.0
        cb.record_step_call(ts=now - 0.5)

        for state in (
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ):
            result = cb.check_no_step_progress(agent_state=state, now=now)
            assert result is None, f'Watchdog should ignore state {state}'

    def test_watchdog_disabled_when_timeout_zero(self):
        """Setting no_step_progress_timeout_seconds <= 0 disables the watchdog."""
        config = CircuitBreakerConfig(
            enabled=True,
            no_step_progress_timeout_seconds=0.0,
        )
        cb = CircuitBreaker(config)
        now = 10.0
        cb.record_step_call(ts=now - 999.0)  # Very old call

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=now)

        assert result is None

    def test_watchdog_disabled_when_disabled_in_config(self, cb):
        """Watchdog respects config.enabled = False."""
        cb.config.enabled = False
        now = 10.0
        cb.record_step_call(ts=now - 999.0)

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=now)

        assert result is None

    def test_watchdog_no_false_positive_on_first_call(self, cb):
        """If _last_step_call_ts is None (never called), watchdog is silent."""
        cb._last_step_call_ts = None

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=10.0)

        assert result is None

    def test_watchdog_cooldown_prevents_immediate_second_fatal(self, cb):
        """A second stall after the cooldown window expires triggers auto-recover
        again (not a fatal stop).
        """
        now = 10.0

        # First stall
        cb.record_step_call(ts=now - 0.5)
        cb._auto_recover_attempts = 1
        cb._last_auto_recover_ts = now - 0.2  # 200ms ago — past 150ms cooldown

        result = cb.check_no_step_progress(agent_state=AgentState.RUNNING, now=now)

        # Should be another auto_recover_once, not stop
        assert result is not None
        assert result.action == 'auto_recover_once'
        assert result.tripped is False
        assert cb._auto_recover_attempts == 2

    def test_record_step_call_resets_auto_recover_attempts(self, cb):
        """A successful step call after a stall resets the counter."""
        cb._auto_recover_attempts = 3
        cb._last_auto_recover_ts = 5.0

        cb.record_step_call(ts=10.0)

        assert cb._auto_recover_attempts == 0
        assert cb._last_auto_recover_ts is None

    def test_update_cached_state(self, cb):
        """update_cached_state stores the state for lazy watchdog reads."""
        assert not hasattr(cb, '_cached_state')

        cb.update_cached_state(AgentState.RUNNING)

        assert cb._cached_state == AgentState.RUNNING

    def test_reset_clears_watchdog_state(self, cb):
        """CircuitBreaker.reset() wipes all watchdog state."""
        cb._last_step_call_ts = 99.0
        cb._auto_recover_attempts = 5
        cb._last_auto_recover_ts = 88.0

        cb.reset()

        assert cb._last_step_call_ts is None
        assert cb._auto_recover_attempts == 0
        assert cb._last_auto_recover_ts is None
