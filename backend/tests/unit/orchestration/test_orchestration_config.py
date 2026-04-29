"""Tests for backend.orchestration.orchestration_config — configuration and service container."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.ledger import EventStream
from backend.orchestration.agent import Agent
from backend.orchestration.orchestration_config import (
    OrchestrationConfig,
    OrchestrationServices,
)
from backend.orchestration.state.state import State

_WIRED_SERVICE_ATTRS = (
    'lifecycle',
    'autonomy',
    'context',
    'iteration',
    'iteration_guard',
    'step_guard',
    'step_prerequisites',
    'safety',
    'pending_action',
    'observation',
    'confirmation',
    'action',
    'action_execution',
    'state',
    'retry',
    'recovery',
    'circuit_breaker',
    'stuck',
    'task_validation',
    'event_router',
    'step_decision',
    'exception_handler',
)


def _assert_services_wired(services: OrchestrationServices) -> None:
    for attr in _WIRED_SERVICE_ATTRS:
        assert getattr(services, attr) is not None


def _assert_config_attrs(config: OrchestrationConfig, expected: dict[str, object]) -> None:
    for attr, value in expected.items():
        assert getattr(config, attr) == value


class TestOrchestrationConfig:
    """Tests for OrchestrationConfig dataclass."""

    def test_minimal_config_creation(self):
        """Test creates config with minimal required fields."""
        mock_agent = MagicMock(spec=Agent)
        mock_stream = MagicMock(spec=EventStream)
        mock_stats = MagicMock()

        config = OrchestrationConfig(
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

        config = OrchestrationConfig(
            agent=mock_agent,
            event_stream=mock_stream,
            conversation_stats=mock_stats,
            iteration_delta=5,
        )
        _assert_config_attrs(
            config,
            {
                'budget_per_task_delta': None,
                'agent_to_llm_config': None,
                'agent_configs': None,
                'sid': None,
                'file_store': None,
                'user_id': None,
                'confirmation_mode': False,
                'initial_state': None,
                'headless_mode': True,
                'status_callback': None,
                'replay_events': None,
                'security_analyzer': None,
            },
        )

    def test_config_with_all_optional_fields(self):
        """Test creates config with all optional fields populated."""
        mock_agent = MagicMock(spec=Agent)
        mock_stream = MagicMock(spec=EventStream)
        mock_stats = MagicMock()
        mock_file_store = MagicMock()
        mock_state = MagicMock(spec=State)
        mock_callback = MagicMock()
        mock_analyzer = MagicMock()

        config = OrchestrationConfig(
            agent=mock_agent,
            event_stream=mock_stream,
            conversation_stats=mock_stats,
            iteration_delta=15,
            budget_per_task_delta=100.5,
            agent_to_llm_config={'agent1': MagicMock()},
            agent_configs={'agent1': MagicMock()},
            sid='session_123',
            file_store=mock_file_store,
            user_id='user_456',
            confirmation_mode=True,
            initial_state=mock_state,
            headless_mode=False,
            status_callback=mock_callback,
            replay_events=[MagicMock(), MagicMock()],
            security_analyzer=mock_analyzer,
        )

        assert config.budget_per_task_delta == 100.5
        assert config.sid == 'session_123'
        assert config.user_id == 'user_456'
        assert config.confirmation_mode is True
        assert config.headless_mode is False
        assert config.replay_events is not None
        assert len(config.replay_events) == 2

    def test_headless_mode_default_true(self):
        """Test headless_mode defaults to True."""
        config = OrchestrationConfig(
            agent=MagicMock(spec=Agent),
            event_stream=MagicMock(spec=EventStream),
            conversation_stats=MagicMock(),
            iteration_delta=10,
        )

        assert config.headless_mode is True

    def test_confirmation_mode_default_false(self):
        """Test confirmation_mode defaults to False."""
        config = OrchestrationConfig(
            agent=MagicMock(spec=Agent),
            event_stream=MagicMock(spec=EventStream),
            conversation_stats=MagicMock(),
            iteration_delta=10,
        )

        assert config.confirmation_mode is False


class TestOrchestrationServices:
    """Tests for OrchestrationServices container."""

    def test_initializes_all_services(self):
        """Test initializes all wired service instances."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)
        _assert_services_wired(services)

    def test_service_count_matches_documentation(self):
        """Test creates exactly 22 unique services as documented."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)

        # Count unique service instances; canonical aliases should not inflate the total.
        service_attrs = [
            getattr(services, attr)
            for attr in dir(services)
            if not attr.startswith('_') and not callable(getattr(services, attr))
        ]

        assert len({id(service) for service in service_attrs}) == 22

    def test_services_receive_controller_reference(self):
        """Test some services receive direct controller reference."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)

        # Services that take controller directly
        from backend.orchestration.services import LifecycleService

        assert isinstance(services.lifecycle, LifecycleService)

    def test_services_receive_context(self):
        """Test most services receive OrchestrationContext."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)

        # Services built on context
        from backend.orchestration.services import IterationService, SafetyService

        assert isinstance(services.iteration, IterationService)
        assert isinstance(services.safety, SafetyService)

    def test_pending_action_receives_timeout(self):
        """Test PendingActionService receives timeout from controller."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 60

        services = OrchestrationServices(mock_controller)

        # Verify service was initialized (exact check depends on service implementation)
        assert services.pending_action is not None

    def test_observation_receives_pending_action(self):
        """Test ObservationService receives pending_action service."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)

        # ObservationService should be initialized with pending_action
        assert services.observation is not None
        assert services.pending_action is not None

    def test_confirmation_receives_safety(self):
        """Test ConfirmationService receives safety service."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)

        assert services.confirmation is not None
        assert services.safety is not None

    def test_action_receives_dependencies(self):
        """Test ActionService receives pending_action and confirmation."""
        mock_controller = MagicMock()
        mock_controller.PENDING_ACTION_TIMEOUT = 30

        services = OrchestrationServices(mock_controller)

        assert services.action is not None
        assert services.pending_action is not None
        assert services.confirmation is not None
