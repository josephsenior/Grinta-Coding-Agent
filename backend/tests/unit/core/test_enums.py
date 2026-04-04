"""Tests for backend.core.enums — canonical enumeration types."""

import pytest

from backend.core.enums import (
    ActionConfirmationStatus,
    ActionSecurityRisk,
    ActionType,
    AgentState,
    CircuitState,
    ContentType,
    ErrorCategory,
    ErrorSeverity,
    EventSource,
    ExitReason,
    LifecyclePhase,
    ObservationType,
    QuotaPlan,
    RetryStrategy,
    RuntimeStatus,
)


class TestQuotaPlan:
    """Tests for QuotaPlan enum."""

    def test_enum_value(self):
        """Test QuotaPlan has UNLIMITED value."""
        assert QuotaPlan.UNLIMITED.value == 'unlimited'

    def test_enum_count(self):
        """Test QuotaPlan has exactly 1 value."""
        assert len(list(QuotaPlan)) == 1

    def test_enum_equality(self):
        """Test QuotaPlan enum equality."""
        assert QuotaPlan.UNLIMITED == QuotaPlan.UNLIMITED

    def test_enum_membership(self):
        """Test QuotaPlan enum membership."""
        assert QuotaPlan.UNLIMITED in QuotaPlan
        # String values ARE in str enums
        assert 'unlimited' in QuotaPlan


class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_enum_values(self):
        """Test CircuitState has expected values."""
        assert CircuitState.CLOSED.value == 'closed'
        assert CircuitState.OPEN.value == 'open'
        assert CircuitState.HALF_OPEN.value == 'half_open'

    def test_enum_count(self):
        """Test CircuitState has exactly 3 values."""
        assert len(list(CircuitState)) == 3

    def test_enum_ordering(self):
        """Test CircuitState enum ordering."""
        states = list(CircuitState)
        assert CircuitState.CLOSED in states
        assert CircuitState.OPEN in states
        assert CircuitState.HALF_OPEN in states


class TestErrorSeverity:
    """Tests for ErrorSeverity enum."""

    def test_enum_values(self):
        """Test ErrorSeverity has expected values."""
        assert ErrorSeverity.INFO.value == 'info'
        assert ErrorSeverity.WARNING.value == 'warning'
        assert ErrorSeverity.ERROR.value == 'error'
        assert ErrorSeverity.CRITICAL.value == 'critical'

    def test_enum_count(self):
        """Test ErrorSeverity has exactly 4 values."""
        assert len(list(ErrorSeverity)) == 4

    def test_severity_hierarchy(self):
        """Test ErrorSeverity can be compared."""
        assert ErrorSeverity.INFO != ErrorSeverity.CRITICAL
        assert ErrorSeverity.WARNING == ErrorSeverity.WARNING


class TestErrorCategory:
    """Tests for ErrorCategory enum."""

    def test_enum_values(self):
        """Test ErrorCategory has expected values."""
        assert ErrorCategory.USER_INPUT.value == 'user_input'
        assert ErrorCategory.SYSTEM.value == 'system'
        assert ErrorCategory.RATE_LIMIT.value == 'rate_limit'
        assert ErrorCategory.AUTHENTICATION.value == 'authentication'
        assert ErrorCategory.NETWORK.value == 'network'
        assert ErrorCategory.AI_MODEL.value == 'ai_model'
        assert ErrorCategory.CONFIGURATION.value == 'configuration'

    def test_enum_count(self):
        """Test ErrorCategory has exactly 7 values."""
        assert len(list(ErrorCategory)) == 7

    def test_enum_string_conversion(self):
        """Test ErrorCategory string conversion."""
        assert str(ErrorCategory.USER_INPUT) == 'ErrorCategory.USER_INPUT'


class TestContentType:
    """Tests for ContentType enum."""

    def test_enum_values(self):
        """Test ContentType has expected values."""
        assert ContentType.TEXT.value == 'text'
        assert ContentType.IMAGE_URL.value == 'image_url'

    def test_enum_count(self):
        """Test ContentType has exactly 2 values."""
        assert len(list(ContentType)) == 2


class TestActionType:
    """Tests for ActionType enum."""

    def test_core_action_types(self):
        """Test ActionType has core action values."""
        assert ActionType.MESSAGE.value == 'message'
        assert ActionType.START.value == 'start'
        assert ActionType.READ.value == 'read'
        assert ActionType.WRITE.value == 'write'
        assert ActionType.EDIT.value == 'edit'
        assert ActionType.FINISH.value == 'finish'

    def test_control_action_types(self):
        """Test ActionType has control action values."""
        assert ActionType.PAUSE.value == 'pause'
        assert ActionType.RESUME.value == 'resume'
        assert ActionType.STOP.value == 'stop'

    def test_special_action_types(self):
        """Test ActionType has special action values."""
        assert ActionType.THINK.value == 'think'
        assert ActionType.NULL.value == 'null'
        assert ActionType.REJECT.value == 'reject'

    def test_enum_minimum_count(self):
        """Test ActionType has at least 15 action types."""
        assert len(list(ActionType)) >= 15


class TestObservationType:
    """Tests for ObservationType enum."""

    def test_core_observation_types(self):
        """Test ObservationType has core observation values."""
        assert ObservationType.READ.value == 'read'
        assert ObservationType.WRITE.value == 'write'
        assert ObservationType.ERROR.value == 'error'
        assert ObservationType.NULL.value == 'null'

    def test_context_observation_types(self):
        """Test ObservationType has context observation values."""
        assert ObservationType.MESSAGE.value == 'message'
        assert ObservationType.SUCCESS.value == 'success'

    def test_enum_minimum_count(self):
        """Test ObservationType has at least 10 observation types."""
        assert len(list(ObservationType)) >= 10


class TestAgentState:
    """Tests for AgentState enum."""

    def test_lifecycle_states(self):
        """Test AgentState lifecycle values."""
        assert AgentState.LOADING.value == 'loading'
        assert AgentState.RUNNING.value == 'running'
        assert AgentState.STOPPED.value == 'stopped'
        assert AgentState.FINISHED.value == 'finished'
        assert AgentState.ERROR.value == 'error'

    def test_user_interaction_states(self):
        """Test AgentState user interaction values."""
        assert AgentState.AWAITING_USER_INPUT.value == 'awaiting_user_input'
        assert (
            AgentState.AWAITING_USER_CONFIRMATION.value == 'awaiting_user_confirmation'
        )
        assert AgentState.USER_CONFIRMED.value == 'user_confirmed'
        assert AgentState.USER_REJECTED.value == 'user_rejected'

    def test_enum_count(self):
        """Test AgentState has at least 10 values."""
        assert len(list(AgentState)) >= 10

    def test_state_transitions(self):
        """Test AgentState values are distinct."""
        assert AgentState.LOADING != AgentState.RUNNING
        assert AgentState.RUNNING != AgentState.FINISHED
        assert AgentState.FINISHED != AgentState.ERROR


class TestLifecyclePhase:
    """Tests for LifecyclePhase enum."""

    def test_enum_values(self):
        """Test LifecyclePhase has expected values."""
        assert LifecyclePhase.INITIALIZING.value == 'initializing'
        assert LifecyclePhase.ACTIVE.value == 'active'
        assert LifecyclePhase.CLOSING.value == 'closing'
        assert LifecyclePhase.CLOSED.value == 'closed'

    def test_enum_count(self):
        """Test LifecyclePhase has exactly 4 values."""
        assert len(list(LifecyclePhase)) == 4


class TestActionConfirmationStatus:
    """Tests for ActionConfirmationStatus enum."""

    def test_enum_values(self):
        """Test ActionConfirmationStatus has expected values."""
        assert ActionConfirmationStatus.CONFIRMED.value == 'confirmed'
        assert ActionConfirmationStatus.REJECTED.value == 'rejected'
        assert (
            ActionConfirmationStatus.AWAITING_CONFIRMATION.value
            == 'awaiting_confirmation'
        )

    def test_enum_count(self):
        """Test ActionConfirmationStatus has exactly 3 values."""
        assert len(list(ActionConfirmationStatus)) == 3

    def test_phase_equality(self):
        """Test ActionConfirmationStatus equality."""
        assert ActionConfirmationStatus.CONFIRMED == ActionConfirmationStatus.CONFIRMED
        assert ActionConfirmationStatus.CONFIRMED != ActionConfirmationStatus.REJECTED


class TestActionSecurityRisk:
    """Tests for ActionSecurityRisk enum."""

    def test_enum_values(self):
        """Test ActionSecurityRisk has expected values."""
        assert ActionSecurityRisk.UNKNOWN.value == -1
        assert ActionSecurityRisk.LOW.value == 0
        assert ActionSecurityRisk.MEDIUM.value == 1
        assert ActionSecurityRisk.HIGH.value == 2

    def test_enum_count(self):
        """Test ActionSecurityRisk has exactly 4 values."""
        assert len(list(ActionSecurityRisk)) == 4

    def test_risk_ordering(self):
        """Test ActionSecurityRisk values can be compared."""
        assert ActionSecurityRisk.LOW.value < ActionSecurityRisk.MEDIUM.value
        assert ActionSecurityRisk.MEDIUM.value < ActionSecurityRisk.HIGH.value
        assert ActionSecurityRisk.UNKNOWN.value < ActionSecurityRisk.LOW.value


class TestRetryStrategy:
    """Tests for RetryStrategy enum."""

    def test_enum_values(self):
        """Test RetryStrategy has expected values."""
        assert RetryStrategy.EXPONENTIAL.value == 'exponential'
        assert RetryStrategy.LINEAR.value == 'linear'
        assert RetryStrategy.FIXED.value == 'fixed'
        assert RetryStrategy.IMMEDIATE.value == 'immediate'

    def test_enum_count(self):
        """Test RetryStrategy has exactly 4 values."""
        assert len(list(RetryStrategy)) == 4


class TestRuntimeStatus:
    """Tests for RuntimeStatus enum."""

    def test_lifecycle_statuses(self):
        """Test RuntimeStatus has lifecycle values."""
        assert RuntimeStatus.UNKNOWN.value == 'UNKNOWN'
        assert RuntimeStatus.STOPPED.value == 'STATUS$STOPPED'
        assert RuntimeStatus.READY.value == 'STATUS$READY'
        assert RuntimeStatus.ERROR.value == 'STATUS$ERROR'

    def test_startup_statuses(self):
        """Test RuntimeStatus has startup values."""
        assert RuntimeStatus.BUILDING_RUNTIME.value == 'STATUS$BUILDING_RUNTIME'
        assert RuntimeStatus.STARTING_RUNTIME.value == 'STATUS$STARTING_RUNTIME'
        assert RuntimeStatus.RUNTIME_STARTED.value == 'STATUS$RUNTIME_STARTED'

    def test_error_statuses(self):
        """Test RuntimeStatus has error values."""
        assert (
            RuntimeStatus.ERROR_RUNTIME_DISCONNECTED.value
            == 'STATUS$ERROR_RUNTIME_DISCONNECTED'
        )
        assert (
            RuntimeStatus.ERROR_LLM_AUTHENTICATION.value
            == 'STATUS$ERROR_LLM_AUTHENTICATION'
        )

    def test_enum_minimum_count(self):
        """Test RuntimeStatus has at least 10 values."""
        assert len(list(RuntimeStatus)) >= 10


class TestExitReason:
    """Tests for ExitReason enum."""

    def test_enum_values(self):
        """Test ExitReason has expected values."""
        assert ExitReason.INTENTIONAL.value == 'intentional'
        assert ExitReason.INTERRUPTED.value == 'interrupted'
        assert ExitReason.ERROR.value == 'error'

    def test_enum_count(self):
        """Test ExitReason has exactly 3 values."""
        assert len(list(ExitReason)) == 3


class TestEventSource:
    """Tests for EventSource enum."""

    def test_enum_values(self):
        """Test EventSource has expected values."""
        assert EventSource.AGENT.value == 'agent'
        assert EventSource.USER.value == 'user'
        assert EventSource.ENVIRONMENT.value == 'environment'

    def test_enum_count(self):
        """Test EventSource has exactly 3 values."""
        assert len(list(EventSource)) == 3


class TestEnumUsagePatterns:
    """Tests for common enum usage patterns."""

    def test_enum_iteration(self):
        """Test iterating over enum values."""
        states = list(CircuitState)
        assert len(states) == 3
        assert CircuitState.CLOSED in states

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        state = CircuitState('closed')
        assert state == CircuitState.CLOSED

    def test_enum_name_attribute(self):
        """Test enum name attribute."""
        assert QuotaPlan.UNLIMITED.name == 'UNLIMITED'
        assert CircuitState.CLOSED.name == 'CLOSED'

    def test_enum_value_attribute(self):
        """Test enum value attribute."""
        assert QuotaPlan.UNLIMITED.value == 'unlimited'
        assert ErrorSeverity.ERROR.value == 'error'

    def test_enum_invalid_value(self):
        """Test creating enum from invalid value raises error."""
        with pytest.raises(ValueError):
            CircuitState('INVALID')

    def test_multiple_enum_namespaces(self):
        """Test different enums have separate namespaces."""
        # ERROR exists in both ErrorSeverity and AgentState
        assert ErrorSeverity.ERROR.value == 'error'
        assert AgentState.ERROR.value == 'error'
        # Both are str enums with same value, so they're equal
        # But they're different types
        assert type(ErrorSeverity.ERROR) is not type(AgentState.ERROR)

    def test_enum_hash_stability(self):
        """Test enum members are hashable and stable."""
        state_set = {CircuitState.CLOSED, CircuitState.OPEN}
        assert CircuitState.CLOSED in state_set
        assert CircuitState.HALF_OPEN not in state_set

    def test_enum_bool_context(self):
        """Test enums are truthy in boolean context."""
        assert QuotaPlan.UNLIMITED
        assert CircuitState.CLOSED
        assert not (CircuitState.CLOSED == CircuitState.OPEN)
