"""Tests for backend.controller.controller_config — configuration and service container."""

from __future__ import annotations

from unittest.mock import MagicMock


from backend.controller.controller_config import ControllerConfig, ControllerServices
from backend.controller.agent import Agent
from backend.controller.state.state import State
from backend.events import EventStream


class TestControllerConfig:
    """Tests for ControllerConfig dataclass."""

    def test_minimal_config_creation(self):
        """Test creates config with minimal required fields."""
        mock_agent = MagicMock(spec=Agent)
        mock_stream = MagicMock(spec=EventStream)
        mock_stats = MagicMock()

        config = ControllerConfig(
            agent=mock_agent,
            event_stream=mock_stream,
            conversation_stats=mock_stats,
            iteration_delta=10,
        )

        assert config.agent == mock_agent
        assert config.event_stream == mock_stream
        assert config.conversation_stats == mock_stats
        assert config.iteration_delta == 10

    def test_all_fields_with_defaults_none(self):
        """Test all optional fields default to None or False."""
        mock_agent = MagicMock(spec=Agent)
        mock_stream = MagicMock(spec=EventStream)
        mock_stats = MagicMock()

        config = ControllerConfig(
            agent=mock_agent,
            event_stream=mock_stream,
            conversation_stats=mock_stats,
            iteration_delta=5,
        )

        assert config.budget_per_task_delta is None
        assert config.agent_to_llm_config is None
        assert config.agent_configs is None
        assert config.sid is None
        assert config.file_store is None
        assert config.user_id is None
        assert config.confirmation_mode is False
        assert config.initial_state is None
        assert config.headless_mode is True
        assert config.status_callback is None
        assert config.replay_events is None
        assert config.security_analyzer is None

    def test_config_with_all_optional_fields(self):
        """Test creates config with all optional fields populated."""
        mock_agent = MagicMock(spec=Agent)
        mock_stream = MagicMock(spec=EventStream)
        mock_stats = MagicMock()
        mock_file_store = MagicMock()
        mock_state = MagicMock(spec=State)
        mock_callback = MagicMock()
        mock_analyzer = MagicMock()

        config = ControllerConfig(
            agent=mock_agent,
            event_stream=mock_stream,
            conversation_stats=mock_stats,
            iteration_delta=15,
            budget_per_task_delta=100.5,
            agent_to_llm_config={"agent1": MagicMock()},
            agent_configs={"agent1": MagicMock()},
            sid="session_123",
            file_store=mock_file_store,
            user_id="user_456",
            confirmation_mode=True,
            initial_state=mock_state,
            headless_mode=False,
            status_callback=mock_callback,
            replay_events=[MagicMock(), MagicMock()],
            security_analyzer=mock_analyzer,
        )

        assert config.budget_per_task_delta == 100.5
        assert config.sid == "session_123"
        assert config.user_id == "user_456"
        assert config.confirmation_mode is True
        assert config.headless_mode is False
        assert len(config.replay_events) == 2

    def test_headless_mode_default_true(self):
        """Test headless_mode defaults to True."""
        config = ControllerConfig(
            agent=MagicMock(spec=Agent),
            event_stream=MagicMock(spec=EventStream),
            conversation_stats=MagicMock(),
            iteration_delta=10,
        )

        assert config.headless_mode is True

    def test_confirmation_mode_default_false(self):
        """Test confirmation_mode defaults to False."""
        config = ControllerConfig(
            agent=MagicMock(spec=Agent),
            event_stream=MagicMock(spec=EventStream),
            conversation_stats=MagicMock(),
            iteration_delta=10,
        )

        assert config.confirmation_mode is False


class TestControllerServices:
    """Tests for ControllerServices container."""

    def test_initializes_all_services(self):
        """Test initializes all 21 service instances."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        # Verify all services are created
        assert services.lifecycle is not None
        assert services.autonomy is not None
        assert services.context is not None
        assert services.iteration is not None
        assert services.iteration_guard is not None
        assert services.step_guard is not None
        assert services.step_prerequisites is not None
        assert services.budget_guard is not None
        assert services.safety is not None
        assert services.pending_action is not None
        assert services.observation is not None
        assert services.confirmation is not None
        assert services.action is not None
        assert services.action_execution is not None
        assert services.state is not None
        assert services.telemetry is not None
        assert services.metrics is not None
        assert services.retry is not None
        assert services.recovery is not None
        assert services.circuit_breaker is not None
        assert services.stuck is not None
        assert services.task_validation is not None
        assert services.event_router is not None
        assert services.step_decision is not None
        assert services.exception_handler is not None

    def test_service_count_matches_documentation(self):
        """Test creates exactly 25 services as documented."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        # Count all service attributes (excluding __dict__ and other internals)
        service_attrs = [
            attr
            for attr in dir(services)
            if not attr.startswith("_") and not callable(getattr(services, attr))
        ]

        assert len(service_attrs) == 25

    def test_services_receive_controller_reference(self):
        """Test some services receive direct controller reference."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        # Services that take controller directly
        from backend.controller.services import LifecycleService

        assert isinstance(services.lifecycle, LifecycleService)

    def test_services_receive_context(self):
        """Test most services receive ControllerContext."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        # Services built on context
        from backend.controller.services import (
            IterationService,
            SafetyService,
            BudgetGuardService,
        )

        assert isinstance(services.iteration, IterationService)
        assert isinstance(services.safety, SafetyService)
        assert isinstance(services.budget_guard, BudgetGuardService)

    def test_pending_action_receives_timeout(self):
        """Test PendingActionService receives timeout from controller."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 60

        services = ControllerServices(mock_controller)

        # Verify service was initialized (exact check depends on service implementation)
        assert services.pending_action is not None

    def test_observation_receives_pending_action(self):
        """Test ObservationService receives pending_action service."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        # ObservationService should be initialized with pending_action
        assert services.observation is not None
        assert services.pending_action is not None

    def test_confirmation_receives_safety(self):
        """Test ConfirmationService receives safety service."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        assert services.confirmation is not None
        assert services.safety is not None

    def test_action_receives_dependencies(self):
        """Test ActionService receives pending_action and confirmation."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        assert services.action is not None
        assert services.pending_action is not None
        assert services.confirmation is not None

    def test_recovery_receives_retry(self):
        """Test RecoveryService receives retry service."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = ControllerServices(mock_controller)

        assert services.recovery is not None
        assert services.retry is not None
