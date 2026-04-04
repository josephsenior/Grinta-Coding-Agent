"""Unit tests for backend.orchestration.services.autonomy_service — AutonomyService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ── Helpers ──────────────────────────────────────────────────────────


def _make_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.circuit_breaker_service = MagicMock()
    ctrl.retry_service = MagicMock()
    ctrl.autonomy_controller = None
    ctrl.safety_validator = None
    ctrl.task_validator = None
    ctrl.PENDING_ACTION_TIMEOUT = 0.0
    ctrl._add_system_message = MagicMock()
    return ctrl


def _make_agent(agent_config=None) -> MagicMock:
    agent = MagicMock()
    agent.config = agent_config
    return agent


def _make_agent_config(
    *,
    safety_enabled: bool = False,
    completion_validation: bool = False,
) -> MagicMock:
    from backend.core.config.agent_config import AgentConfig

    cfg = MagicMock(spec=AgentConfig)
    cfg.safety = MagicMock()
    cfg.safety.enable_mandatory_validation = safety_enabled
    cfg.enable_completion_validation = completion_validation
    return cfg


# ── AutonomyService.initialize ───────────────────────────────────────


class TestAutonomyServiceInitialize:
    def test_null_agent_config_sets_defaults(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        svc = AutonomyService(ctrl)

        agent = _make_agent(agent_config=None)
        svc.initialize(agent)

        ctrl.circuit_breaker_service.reset.assert_called_once()
        ctrl.retry_service.reset_retry_metrics.assert_called_once()
        assert ctrl.autonomy_controller is None
        assert ctrl.safety_validator is None
        assert ctrl.task_validator is None
        assert ctrl.PENDING_ACTION_TIMEOUT == 0.0

    def test_wrong_type_agent_config(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        svc = AutonomyService(ctrl)

        agent = _make_agent(agent_config='not_a_config')
        svc.initialize(agent)

        assert ctrl.autonomy_controller is None
        assert ctrl.safety_validator is None
        assert ctrl.task_validator is None

    def test_valid_config_creates_autonomy_controller(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        svc = AutonomyService(ctrl)

        agent_config = _make_agent_config()
        agent = _make_agent(agent_config=agent_config)

        with (
            patch('backend.orchestration.autonomy.AutonomyController') as mock_ac,
            patch(
                'backend.orchestration.services.autonomy_service.SafetyValidator',
                create=True,
            ),
            patch(
                'backend.orchestration.services.autonomy_service.CompositeValidator',
                create=True,
            ),
        ):
            svc.initialize(agent)
            mock_ac.assert_called_once_with(agent_config)
            assert ctrl.autonomy_controller == mock_ac.return_value

        ctrl.circuit_breaker_service.reset.assert_called_once()
        ctrl.retry_service.reset_retry_metrics.assert_called_once()
        ctrl.circuit_breaker_service.configure.assert_called_once_with(agent_config)


# ── _initialize_safety_validator ─────────────────────────────────────


class TestInitializeSafetyValidator:
    def test_disabled_safety(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        svc = AutonomyService(ctrl)

        agent_config = _make_agent_config(safety_enabled=False)
        agent = _make_agent(agent_config=agent_config)

        svc._initialize_safety_validator(agent)
        assert ctrl.safety_validator is None

    def test_enabled_safety(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        svc = AutonomyService(ctrl)

        agent_config = _make_agent_config(safety_enabled=True)
        agent = _make_agent(agent_config=agent_config)

        with patch('backend.orchestration.safety_validator.SafetyValidator') as mock_sv:
            svc._initialize_safety_validator(agent)
            mock_sv.assert_called_once_with(agent_config.safety)
            assert ctrl.safety_validator == mock_sv.return_value


# ── _initialize_task_validator ───────────────────────────────────────


class TestInitializeTaskValidator:
    def test_disabled_validation(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        svc = AutonomyService(ctrl)

        agent_config = _make_agent_config(completion_validation=False)
        agent = _make_agent(agent_config=agent_config)

        svc._initialize_task_validator(agent)
        assert ctrl.task_validator is None
        assert ctrl.PENDING_ACTION_TIMEOUT == 0.0

    def test_enabled_validation(self):
        from backend.orchestration.services.autonomy_service import AutonomyService

        ctrl = _make_controller()
        ctrl._add_system_message = MagicMock()
        svc = AutonomyService(ctrl)

        agent_config = _make_agent_config(completion_validation=True)
        agent = _make_agent(agent_config=agent_config)

        with patch('backend.validation.task_validator.CompositeValidator') as mock_cv:
            svc._initialize_task_validator(agent)
            mock_cv.assert_called_once()
            assert ctrl.task_validator == mock_cv.return_value
            assert ctrl.PENDING_ACTION_TIMEOUT == 0.0
            ctrl._add_system_message.assert_called_once()
