"""Unit tests for backend.orchestration.agent_circuit_breaker module.

Tests cover:
- CircuitBreakerConfig dataclass
- CircuitBreakerResult dataclass
- CircuitBreaker initialization
- check() method with various trip conditions
- record_error, record_success tracking
- record_high_risk_action, record_stuck_detection
- Error rate calculation
- reset() functionality
"""

from unittest.mock import MagicMock

from backend.orchestration.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerResult,
)
from backend.ledger.action import ActionSecurityRisk


class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig dataclass."""

    def test_config_defaults(self):
        """CircuitBreakerConfig should have default values."""
        config = CircuitBreakerConfig()

        assert config.enabled is True
        assert config.max_consecutive_errors == 5
        assert config.max_high_risk_actions == 10
        assert config.max_stuck_detections == 15
        assert config.max_error_rate == 0.5
        assert config.error_rate_window == 10

    def test_config_custom_values(self):
        """CircuitBreakerConfig should accept custom values."""
        config = CircuitBreakerConfig(
            enabled=False,
            max_consecutive_errors=10,
            max_high_risk_actions=20,
            max_stuck_detections=5,
            max_error_rate=0.75,
            error_rate_window=15,
        )

        assert config.enabled is False
        assert config.max_consecutive_errors == 10
        assert config.max_high_risk_actions == 20
        assert config.max_stuck_detections == 5
        assert config.max_error_rate == 0.75
        assert config.error_rate_window == 15

    def test_scaled_disabled_adaptive(self):
        """Should return self if adaptive is disabled."""
        config = CircuitBreakerConfig(adaptive=False)
        scaled = config.scaled(complexity=10, max_iterations=500)
        assert scaled is config

    def test_scaled_complexity_levels(self):
        """Should scale thresholds based on complexity (50-66)."""
        config = CircuitBreakerConfig(adaptive=True)

        # Complexity 3 (1.0x)
        c3 = config.scaled(complexity=3, max_iterations=100)
        assert c3.max_consecutive_errors == config.max_consecutive_errors

        # Complexity 6 (1.5x)
        # 1.5x * 1.0 (itr) = 1.5x
        c6 = config.scaled(complexity=6, max_iterations=100)
        assert c6.max_consecutive_errors == int(config.max_consecutive_errors * 1.5)

        # Complexity 10 (2.0x)
        c10 = config.scaled(complexity=10, max_iterations=100)
        assert c10.max_consecutive_errors == config.max_consecutive_errors * 2

    def test_scaled_iteration_multiplier(self):
        """Should scale thresholds based on iteration budget (58)."""
        config = CircuitBreakerConfig(adaptive=True)

        # 500 iterations (max budget shift: 1.0 + (500-100)/400 = 2.0 -> capped at 1.5)
        # complexity 10 (2.0x) -> total scale 2.0 * 1.5 = 3.0x
        c500 = config.scaled(complexity=10, max_iterations=500)
        assert c500.max_consecutive_errors == config.max_consecutive_errors * 3


class TestCircuitBreakerResult:
    """Test CircuitBreakerResult dataclass."""

    def test_result_creation(self):
        """CircuitBreakerResult should store trip information."""
        result = CircuitBreakerResult(
            tripped=True,
            reason="Too many errors",
            action="pause",
            recommendation="Review logs",
        )

        assert result.tripped is True
        assert result.reason == "Too many errors"
        assert result.action == "pause"
        assert result.recommendation == "Review logs"

    def test_result_default_recommendation(self):
        """CircuitBreakerResult should have empty default recommendation."""
        result = CircuitBreakerResult(
            tripped=False,
            reason="All good",
            action="continue",
        )

        assert result.recommendation == ""


class TestCircuitBreakerInit:
    """Test CircuitBreaker initialization."""

    def test_init_with_config(self):
        """Should initialize with provided config."""
        config = CircuitBreakerConfig(max_consecutive_errors=3)
        breaker = CircuitBreaker(config)

        assert breaker.config == config
        assert breaker.consecutive_errors == 0
        assert breaker.high_risk_action_count == 0
        assert breaker.stuck_detection_count == 0
        assert not breaker.recent_errors
        assert not breaker.recent_actions_success

    def test_init_creates_deques_with_maxlen(self):
        """Deques should have maxlen based on config."""
        config = CircuitBreakerConfig(error_rate_window=10)
        breaker = CircuitBreaker(config)

        # maxlen should be window * 2
        assert breaker.recent_errors.maxlen == 20
        assert breaker.recent_actions_success.maxlen == 20


class TestCheckMethod:
    """Test check() method."""

    def test_check_disabled_breaker_returns_not_tripped(self):
        """Disabled circuit breaker should never trip."""
        config = CircuitBreakerConfig(enabled=False)
        breaker = CircuitBreaker(config)
        state = MagicMock()
        state.history = []

        result = breaker.check(state)

        assert result.tripped is False
        assert result.action == "continue"
        assert "disabled" in result.reason.lower()

    def test_check_no_issues_returns_not_tripped(self):
        """Check should pass when no issues detected."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)
        state = MagicMock()
        state.history = []

        result = breaker.check(state)

        assert result.tripped is False
        assert result.reason == "All checks passed"
        assert result.action == "continue"

    def test_check_consecutive_errors_trips(self):
        """Should trip when consecutive errors exceed threshold."""
        config = CircuitBreakerConfig(max_consecutive_errors=3)
        breaker = CircuitBreaker(config)

        # Record 3 consecutive errors
        for _ in range(3):
            breaker.record_error(RuntimeError("Test error"))

        state = MagicMock()
        state.history = []
        result = breaker.check(state)

        assert result.tripped is True
        assert "consecutive errors" in result.reason.lower()
        assert result.action == "pause"
        assert "review" in result.recommendation.lower()

    def test_check_high_risk_actions_trips(self):
        """Should trip when high-risk actions exceed threshold."""
        config = CircuitBreakerConfig(max_high_risk_actions=3)
        breaker = CircuitBreaker(config)

        # Record 3 high-risk actions
        for _ in range(3):
            breaker.record_high_risk_action(ActionSecurityRisk.HIGH)

        state = MagicMock()
        state.history = []
        result = breaker.check(state)

        assert result.tripped is True
        assert "high-risk actions" in result.reason.lower()
        assert result.action == "pause"

    def test_check_stuck_detections_trips(self):
        """Should trip when stuck detections exceed threshold."""
        config = CircuitBreakerConfig(max_stuck_detections=2)
        breaker = CircuitBreaker(config)

        # Record 2 stuck detections
        for _ in range(2):
            breaker.record_stuck_detection()

        state = MagicMock()
        state.history = []
        result = breaker.check(state)

        assert result.tripped is True
        assert "stuck loop detection" in result.reason.lower()
        assert result.action == "stop"

    def test_check_error_rate_trips(self):
        """Should trip when error rate exceeds threshold."""
        config = CircuitBreakerConfig(
            max_error_rate=0.5,  # 50%
            error_rate_window=10,
        )
        breaker = CircuitBreaker(config)

        # Record 10 actions with 6 errors (60% error rate)
        for i in range(10):
            if i < 6:
                breaker.record_error(RuntimeError("Error"))
            else:
                breaker.record_success()

        state = MagicMock()
        state.history = []
        result = breaker.check(state)

        assert result.tripped is True
        assert "error rate too high" in result.reason.lower()
        assert result.action == "pause"

    def test_check_error_rate_needs_minimum_samples(self):
        """Error rate check should require minimum sample size."""
        config = CircuitBreakerConfig(
            max_error_rate=0.5,
            error_rate_window=10,
            max_consecutive_errors=100,  # High to avoid consecutive error trip
        )
        breaker = CircuitBreaker(config)

        # Record only 5 actions (below window size) with alternating success/error
        # to avoid consecutive error threshold
        for i in range(5):
            if i % 2 == 0:
                breaker.record_error(RuntimeError("Error"))
            else:
                breaker.record_success()

        state = MagicMock()
        state.history = []
        result = breaker.check(state)

        # Should not trip due to insufficient samples (only 5, need 10)
        assert result.tripped is False


class TestRecordError:
    """Test record_error method."""

    def test_record_error_increments_counter(self):
        """record_error should increment consecutive error counter."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_error(RuntimeError("Error 1"))
        assert breaker.consecutive_errors == 1

        breaker.record_error(ValueError("Error 2"))
        assert breaker.consecutive_errors == 2

    def test_record_error_adds_to_recent_errors(self):
        """record_error should add error to recent errors deque."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        error = RuntimeError("Test error")
        breaker.record_error(error)

        assert len(breaker.recent_errors) == 1
        assert "Test error" in breaker.recent_errors[0]

    def test_record_error_adds_false_to_actions_success(self):
        """record_error should mark action as unsuccessful."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_error(RuntimeError("Error"))

        assert len(breaker.recent_actions_success) == 1
        assert breaker.recent_actions_success[0] is False


class TestRecordSuccess:
    """Test record_success method."""

    def test_record_success_resets_consecutive_errors(self):
        """record_success should reset consecutive error counter."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_error(RuntimeError("Error"))
        assert breaker.consecutive_errors == 1

        breaker.record_success()
        assert breaker.consecutive_errors == 0

    def test_record_success_adds_true_to_actions_success(self):
        """record_success should mark action as successful."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_success()

        assert len(breaker.recent_actions_success) == 1
        assert breaker.recent_actions_success[0] is True


class TestRecordHighRiskAction:
    """Test record_high_risk_action method."""

    def test_record_high_risk_increments_counter(self):
        """HIGH risk actions should increment counter."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_high_risk_action(ActionSecurityRisk.HIGH)
        assert breaker.high_risk_action_count == 1

        breaker.record_high_risk_action(ActionSecurityRisk.HIGH)
        assert breaker.high_risk_action_count == 2

    def test_record_low_risk_does_not_increment(self):
        """LOW/MEDIUM risk actions should not increment counter."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_high_risk_action(ActionSecurityRisk.LOW)
        assert breaker.high_risk_action_count == 0

        breaker.record_high_risk_action(ActionSecurityRisk.MEDIUM)
        assert breaker.high_risk_action_count == 0


class TestRecordStuckDetection:
    """Test record_stuck_detection method."""

    def test_record_stuck_detection_increments_counter(self):
        """record_stuck_detection should increment counter."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        breaker.record_stuck_detection()
        assert breaker.stuck_detection_count == 1

        breaker.record_stuck_detection()
        assert breaker.stuck_detection_count == 2


class TestCalculateErrorRate:
    """Test _calculate_error_rate method."""

    def test_calculate_error_rate_empty_history(self):
        """Error rate should be 0.0 with empty history."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        rate = breaker._calculate_error_rate()
        assert rate == 0.0

    def test_calculate_error_rate_all_errors(self):
        """Error rate should be 1.0 when all actions fail."""
        config = CircuitBreakerConfig(error_rate_window=5)
        breaker = CircuitBreaker(config)

        for _ in range(5):
            breaker.record_error(RuntimeError("Error"))

        rate = breaker._calculate_error_rate()
        assert rate == 1.0

    def test_calculate_error_rate_all_success(self):
        """Error rate should be 0.0 when all actions succeed."""
        config = CircuitBreakerConfig(error_rate_window=5)
        breaker = CircuitBreaker(config)

        for _ in range(5):
            breaker.record_success()

        rate = breaker._calculate_error_rate()
        assert rate == 0.0

    def test_calculate_error_rate_mixed(self):
        """Error rate should be correct with mixed success/failure."""
        config = CircuitBreakerConfig(error_rate_window=10)
        breaker = CircuitBreaker(config)

        # 3 errors, 7 successes = 30% error rate
        for _ in range(3):
            breaker.record_error(RuntimeError("Error"))
        for _ in range(7):
            breaker.record_success()

        rate = breaker._calculate_error_rate()
        assert rate == 0.3

    def test_calculate_error_rate_uses_window(self):
        """Error rate should only consider recent window."""
        config = CircuitBreakerConfig(error_rate_window=5)
        breaker = CircuitBreaker(config)

        # Old errors (should be outside window)
        for _ in range(10):
            breaker.record_error(RuntimeError("Old error"))

        # Recent successes (within window)
        for _ in range(5):
            breaker.record_success()

        rate = breaker._calculate_error_rate()
        # Should only look at last 5 actions (all successes)
        assert rate == 0.0


class TestReset:
    """Test reset method."""

    def test_reset_clears_all_counters(self):
        """reset should clear all counters and deques."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        # Add some state
        breaker.record_error(RuntimeError("Error"))
        breaker.record_high_risk_action(ActionSecurityRisk.HIGH)
        breaker.record_stuck_detection()

        # Reset
        breaker.reset()

        assert breaker.consecutive_errors == 0
        assert breaker.high_risk_action_count == 0
        assert breaker.stuck_detection_count == 0
        assert not breaker.recent_errors
        assert not breaker.recent_actions_success


class TestCircuitBreakerAdapt:
    """Test adapt method."""

    def test_adapt_scales_config(self):
        """adapt should update breaker config with scaled thresholds (216-232)."""
        config = CircuitBreakerConfig(adaptive=True)
        breaker = CircuitBreaker(config)

        # Adapt complexity 10 (2x multiplier)
        breaker.adapt(complexity=10, max_iterations=100)

        assert breaker.config.max_consecutive_errors == config.max_consecutive_errors * 2
        assert breaker.config.adaptive is False  # newly scaled config has adaptive=False

    def test_adapt_no_scaling_if_new_config_is_same(self):
        """Should skip update if config has adaptive=False."""
        config = CircuitBreakerConfig(adaptive=False)
        breaker = CircuitBreaker(config)

        breaker.adapt(complexity=10, max_iterations=500)
        assert breaker.config is config


class TestUpdateMetrics:
    """Test _update_metrics method."""

    def test_update_metrics_with_error_observations(self):
        """_update_metrics should detect errors in state history."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        from backend.ledger.observation import ErrorObservation

        state = MagicMock()
        # Create error observations in history
        error1 = ErrorObservation(content="Error 1")
        error2 = ErrorObservation(content="Error 2")
        state.history = [error1, error2]

        # Initially consecutive_errors is 0, recent_errors empty (length 0)
        # error_count will be 2. 2 > 0.
        # consecutive_errors increases by 2 - 0 = 2.
        breaker._update_metrics(state)

        # Should have incremented consecutive errors
        assert breaker.consecutive_errors == 2

    def test_update_metrics_with_empty_history(self):
        """_update_metrics should handle empty history."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)

        state = MagicMock()
        state.history = []

        # Should not raise
        breaker._update_metrics(state)
        assert breaker.consecutive_errors == 0
