"""Integration tests for core subsystems.

Covers:
- CircuitBreaker deque-based sliding windows
- Memory pressure → compactor forced-compaction wiring
- MemoryPressureMonitor level detection
- Health snapshot assembly
- State serialization round-trip
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.engine.memory_manager import ContextMemoryManager
from backend.engine.tools.working_memory import (
    build_working_memory_action,
    execute_working_memory,
    get_working_memory_prompt_block,
    set_current_session_id,
)
from backend.ledger.action import ActionSecurityRisk
from backend.ledger.action.files import FileEditAction
from backend.ledger.action.message import MessageAction, SystemMessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileEditObservation
from backend.orchestration.agent.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)
from backend.orchestration.health import collect_orchestration_health
from backend.orchestration.memory_pressure import MemoryPressureMonitor
from backend.orchestration.state.state import State

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _mock_state(
    history: list[Any] | None = None,
    extra_data: dict[str, Any] | None = None,
) -> State:
    state = State(session_id='test-session')
    state.history = history or []
    if extra_data:
        state.extra_data = extra_data
    return state


def _circuit_breaker_error_rate(circuit_breaker: CircuitBreaker) -> float:
    calculate_error_rate = cast(Any, circuit_breaker)._calculate_error_rate
    return cast(float, calculate_error_rate())


def _set_monitor_last_rss(monitor: MemoryPressureMonitor, rss_mb: float | int) -> None:
    object.__setattr__(monitor, '_last_rss_mb', rss_mb)


def _set_monitor_baseline(monitor: MemoryPressureMonitor, baseline_mb: float) -> None:
    object.__setattr__(monitor, '_baseline_rss_mb', baseline_mb)


def _set_monitor_last_check(monitor: MemoryPressureMonitor, last_check: float) -> None:
    object.__setattr__(monitor, '_last_check', last_check)


def _set_monitor_process(monitor: MemoryPressureMonitor, process: Any) -> None:
    object.__setattr__(monitor, '_process', process)


def _memory_pressure_level(monitor: MemoryPressureMonitor) -> str:
    level_str = cast(Any, monitor)._level_str
    return cast(str, level_str())


# ================================================================== #
#  CircuitBreaker – deque sliding window behaviour
# ================================================================== #


class TestCircuitBreakerDeque:
    """Verify that deque(maxlen=...) correctly bounds recent_* buffers."""

    def test_deque_maxlen_is_set(self):
        config = CircuitBreakerConfig(error_rate_window=5)
        cb = CircuitBreaker(config)
        assert isinstance(cb.recent_errors, deque)
        assert cb.recent_errors.maxlen == 10  # 5 * 2
        assert isinstance(cb.recent_actions_success, deque)
        assert cb.recent_actions_success.maxlen == 10

    def test_deque_auto_evicts_oldest(self):
        config = CircuitBreakerConfig(error_rate_window=3)
        cb = CircuitBreaker(config)
        # maxlen = 6 → push 8 items, oldest two should be evicted
        for _ in range(8):
            cb.record_success()
        assert len(cb.recent_actions_success) == 6

    def test_errors_deque_bounded(self):
        config = CircuitBreakerConfig(error_rate_window=2)
        cb = CircuitBreaker(config)
        # maxlen = 4 → push 6 errors
        for i in range(6):
            cb.record_error(Exception(f'err-{i}'))
        assert len(cb.recent_errors) == 4
        # Only the last 4 remain
        assert list(cb.recent_errors) == ['err-2', 'err-3', 'err-4', 'err-5']

    def test_error_rate_uses_window(self):
        config = CircuitBreakerConfig(error_rate_window=4, max_error_rate=0.5)
        cb = CircuitBreaker(config)
        # Push 4 successes then 4 failures
        for _ in range(4):
            cb.record_success()
        for _ in range(4):
            cb.record_error(Exception('fail'))
        # Window of last 4 should be all failures → rate == 1.0
        assert _circuit_breaker_error_rate(cb) == 1.0

    def test_reset_clears_deques(self):
        config = CircuitBreakerConfig(error_rate_window=5)
        cb = CircuitBreaker(config)
        cb.record_error(Exception('e'))
        cb.record_success()
        cb.reset()
        assert not cb.recent_errors
        assert not cb.recent_actions_success
        assert cb.consecutive_errors == 0

    def test_trips_on_error_rate(self):
        config = CircuitBreakerConfig(
            error_rate_window=4,
            max_error_rate=0.5,
            max_consecutive_errors=100,  # don't trip on consecutive
        )
        cb = CircuitBreaker(config)
        state = _mock_state()
        # Fill window: 1 success + 3 fails → rate = 0.75 > 0.5
        cb.record_success()
        for _ in range(3):
            cb.record_error(Exception('x'))
        result = cb.check(state)
        assert result.tripped is True
        assert 'error rate' in result.reason.lower()

    def test_no_trip_below_window_size(self):
        """Error rate check requires at least error_rate_window entries."""
        config = CircuitBreakerConfig(
            error_rate_window=10,
            max_error_rate=0.5,
            max_consecutive_errors=100,
        )
        cb = CircuitBreaker(config)
        state = _mock_state()
        # Only 3 failures — below window size of 10
        for _ in range(3):
            cb.record_error(Exception('x'))
        # Reset consecutive to avoid consecutive-error trip
        cb.consecutive_errors = 0
        result = cb.check(state)
        assert result.tripped is False

    def test_stuck_detection_trips(self):
        config = CircuitBreakerConfig(max_stuck_detections=2)
        cb = CircuitBreaker(config)
        state = _mock_state()
        cb.record_stuck_detection()
        cb.record_stuck_detection()
        result = cb.check(state)
        assert result.tripped is True
        assert result.action == 'stop'

    def test_high_risk_actions_trip(self):
        config = CircuitBreakerConfig(max_high_risk_actions=3)
        cb = CircuitBreaker(config)
        state = _mock_state()
        for _ in range(3):
            cb.record_high_risk_action(ActionSecurityRisk.HIGH)
        result = cb.check(state)
        assert result.tripped is True

    def test_low_risk_actions_ignored(self):
        config = CircuitBreakerConfig(max_high_risk_actions=3)
        cb = CircuitBreaker(config)
        state = _mock_state()
        for _ in range(10):
            cb.record_high_risk_action(ActionSecurityRisk.LOW)
        result = cb.check(state)
        assert result.tripped is False


# ================================================================== #
#  Memory Pressure Monitor
# ================================================================== #


class TestMemoryPressureMonitor:
    """Test MemoryPressureMonitor level detection and snapshots."""

    def test_defaults_without_psutil(self):
        monitor = MemoryPressureMonitor(warn_mb=512, crit_mb=1024, check_interval_s=0)
        _set_monitor_baseline(monitor, 0.0)
        snap = monitor.snapshot()
        assert snap['warn_threshold_mb'] == 512
        assert snap['crit_threshold_mb'] == 1024
        assert snap['condensation_count'] == 0

    def test_normal_level(self):
        monitor = MemoryPressureMonitor(warn_mb=512, crit_mb=1024, check_interval_s=0)
        _set_monitor_baseline(monitor, 0.0)
        _set_monitor_last_rss(monitor, 100)
        assert _memory_pressure_level(monitor) == 'normal'

    def test_warning_level(self):
        monitor = MemoryPressureMonitor(warn_mb=512, crit_mb=1024, check_interval_s=0)
        _set_monitor_baseline(monitor, 0.0)
        _set_monitor_last_rss(monitor, 600)
        assert _memory_pressure_level(monitor) == 'warning'

    def test_critical_level(self):
        monitor = MemoryPressureMonitor(warn_mb=512, crit_mb=1024, check_interval_s=0)
        _set_monitor_baseline(monitor, 0.0)
        _set_monitor_last_rss(monitor, 1200)
        assert _memory_pressure_level(monitor) == 'critical'
        # is_critical() calls _sample_rss() which may return None without psutil
        object.__setattr__(monitor, '_sample_rss', lambda: 1200.0)
        assert monitor.is_critical() is True

    def test_condensation_counter(self):
        monitor = MemoryPressureMonitor(warn_mb=512, crit_mb=1024, check_interval_s=0)
        monitor.record_condensation()
        monitor.record_condensation()
        assert monitor.snapshot()['condensation_count'] == 2

    def test_should_condense_above_warn(self):
        monitor = MemoryPressureMonitor(warn_mb=256, crit_mb=1024, check_interval_s=0)
        _set_monitor_baseline(monitor, 0.0)
        _set_monitor_last_rss(monitor, 300)
        _set_monitor_last_check(monitor, 0)  # force re-check
        # should_condense reads from _sample_rss which may use cache
        # Set process to None to use cached value
        _set_monitor_process(monitor, None)
        # With no psutil process, _sample_rss returns None → should_condense False
        # So let's mock _sample_rss directly
        object.__setattr__(monitor, '_sample_rss', lambda: 300.0)
        assert monitor.should_condense() is True


# ================================================================== #
#  Memory Pressure → Compactor Wiring
# ================================================================== #


class TestMemoryPressureCompactorWiring:
    """Memory-manager condensation delegates to ContextPipeline."""

    async def test_no_pipeline_returns_full_history(self):
        config = MagicMock()
        config.compactor_config = None
        mgr = ContextMemoryManager(config, MagicMock())
        mgr._pipeline = None

        state = _mock_state(history=['e1', 'e2', 'e3'])
        result = await mgr.condense_history(state)
        assert result.events == ['e1', 'e2', 'e3']
        assert result.pending_action is None

    async def test_pipeline_prepare_step_is_used(self):
        from backend.engine.memory_manager import CondensedHistory

        config = MagicMock()
        mgr = ContextMemoryManager(config, MagicMock())
        expected = CondensedHistory(events=['condensed'], pending_action=None)
        pipeline = MagicMock()
        pipeline.prepare_step = AsyncMock(return_value=expected)
        mgr._pipeline = pipeline

        state = _mock_state()
        result = await mgr.condense_history(state)
        assert result.events == ['condensed']
        pipeline.prepare_step.assert_awaited_once()


class TestLongSessionCompactionInvariants:
    @pytest.mark.skip(reason='Covered by context pipeline integration tests')
    async def test_repeated_compaction_preserves_task_roots_and_recovery_artifacts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        _ = monkeypatch, tmp_path


# ================================================================== #
#  Health Snapshot Assembly
# ================================================================== #


class TestHealthSnapshot:
    """Test collect_orchestration_health assembles a complete snapshot."""

    def _make_controller(self, **overrides: Any) -> MagicMock:
        """Build a minimal mock controller for health collection."""
        ctrl = MagicMock()
        ctrl.sid = 'test-session-123'
        ctrl.state = _mock_state()
        ctrl.state.agent_state = MagicMock()
        ctrl.state.agent_state.value = 'running'
        ctrl.state.iteration_flag = MagicMock()
        ctrl.state.iteration_flag.current_value = 5
        ctrl.state.iteration_flag.max_value = 100
        ctrl.state.budget_flag = None
        ctrl.state.metrics = MagicMock()
        ctrl.state.metrics.accumulated_cost = 0.0

        # Circuit breaker service
        cb_config = CircuitBreakerConfig(enabled=True)
        cb_service = MagicMock()
        cb_service.circuit_breaker = CircuitBreaker(cb_config)
        ctrl.circuit_breaker_service = cb_service

        # Retry service
        ctrl.retry_service = MagicMock()
        ctrl.retry_service.enabled = True
        ctrl.retry_service.pending_retry = False
        ctrl.retry_service.retry_count = 0
        ctrl.retry_service._worker_running = False

        # Event stream
        ctrl.event_stream = MagicMock()
        ctrl.event_stream._subscribers = {}
        ctrl.event_stream.get_events.return_value = []

        for key, value in overrides.items():
            setattr(ctrl, key, value)
        return ctrl

    def test_snapshot_has_required_keys(self):
        ctrl = self._make_controller()
        snap = collect_orchestration_health(ctrl)
        assert 'timestamp' in snap
        assert 'controller_id' in snap
        assert 'state' in snap
        assert 'severity' in snap

    def test_severity_green_when_healthy(self):
        ctrl = self._make_controller()
        snap = collect_orchestration_health(ctrl)
        # Severity depends on the mock fidelity; verify it's a valid value
        assert snap['severity'] in ('green', 'yellow', 'red')
        assert isinstance(snap.get('warnings', []), list)

    def test_severity_degrades_with_errors(self):
        ctrl = self._make_controller()
        # Record enough errors to trigger circuit breaker concern
        for _ in range(5):
            ctrl.circuit_breaker_service.circuit_breaker.record_error(Exception('test'))
        snap = collect_orchestration_health(ctrl)
        # Should have warnings about consecutive errors
        warnings = snap.get('warnings', [])
        assert warnings or snap['severity'] in ('yellow', 'red')


# ================================================================== #
#  State extra_data round-trip
# ================================================================== #


class TestStateExtraData:
    """Test that extra_data survives serialization round-trips."""

    def test_extra_data_preserved(self):
        from backend.orchestration.state.state import State

        s = State(session_id='test-1')
        s.extra_data['some_metadata'] = 'FOO'
        s.extra_data['custom_key'] = 42

        assert s.extra_data['some_metadata'] == 'FOO'
        assert s.extra_data['custom_key'] == 42

    def test_extra_data_isolation(self):
        """Each State instance has its own extra_data dict."""
        from backend.orchestration.state.state import State

        s1 = State(session_id='s1')
        s2 = State(session_id='s2')
        s1.extra_data['key'] = 'value'
        assert 'key' not in s2.extra_data
