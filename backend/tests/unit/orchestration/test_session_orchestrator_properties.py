# pyright: reportAttributeAccessIssue=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false
# mypy: disable-error-code="assignment,attr-defined,method-assign,misc"
"""Tests for SessionOrchestrator — the main agent orchestration controller."""
# pylint: disable=protected-access,too-many-lines

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from backend.orchestration.orchestration_config import OrchestrationConfig
from backend.orchestration.session_orchestrator import (
    ERROR_ACTION_NOT_EXECUTED_ERROR,
    ERROR_ACTION_NOT_EXECUTED_STOPPED,
    TRAFFIC_CONTROL_REMINDER,
    SessionOrchestrator,
)
from backend.tests.unit.orchestration._session_orchestrator_helpers import (
    _make_controller,
)


class TestSessionOrchestratorProperties:
    """Test SessionOrchestrator property accessors."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl

    def test_id_returns_config_sid(self):
        assert self.ctrl.id == 'test-sid'

    def test_id_falls_back_to_event_stream_sid(self):
        self.ctrl.config.sid = None
        self.ctrl.config.event_stream.sid = 'stream-sid'
        assert self.ctrl.id == 'stream-sid'

    def test_agent_returns_config_agent(self):
        assert self.ctrl.agent is self.ctrl.config.agent

    def test_event_stream_returns_config_event_stream(self):
        assert self.ctrl.event_stream is self.ctrl.config.event_stream

    def test_state_returns_state_tracker_state(self):
        assert self.ctrl.state is self.ctrl.state_tracker.state

    def test_conversation_stats(self):
        assert self.ctrl.conversation_stats is self.ctrl.config.conversation_stats

    def test_task_id_equals_id(self):
        assert self.ctrl.task_id == self.ctrl.id


@pytest.mark.asyncio
async def test_init_registers_main_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_loops: list[asyncio.AbstractEventLoop] = []

    def _noop(*args: object, **kwargs: object) -> None:
        del args, kwargs

    def _initialize_stuck(state: object) -> None:
        del state

    def _initialize_autonomy(agent: object) -> None:
        del agent

    def _initialize_operation_pipeline(middlewares: object) -> None:
        del middlewares

    def _make_mock() -> MagicMock:
        return MagicMock()

    def _make_scheduler(enabled: object) -> MagicMock:
        return MagicMock(enabled=enabled)

    def _disable_pipeline(_controller: SessionOrchestrator) -> None:
        return None

    def _record_main_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
        captured_loops.append(loop if loop is not None else asyncio.get_running_loop())

    class FakeServices:
        def __init__(self, controller: SessionOrchestrator) -> None:
            self._controller = controller
            self.lifecycle = SimpleNamespace(
                initialize_core_attributes=_noop,
                initialize_state_and_tracking=self._initialize_state_and_tracking,
                initialize_agent_configs=_noop,
            )
            self.stuck = SimpleNamespace(initialize=_initialize_stuck)
            self.autonomy = SimpleNamespace(initialize=_initialize_autonomy)
            self.retry = SimpleNamespace(initialize=_make_mock)
            self.context = SimpleNamespace(
                initialize_operation_pipeline=_initialize_operation_pipeline
            )

        def _initialize_state_and_tracking(
            self, *args: object, **kwargs: object
        ) -> None:
            del args, kwargs
            self._controller.state_tracker = MagicMock()
            self._controller.state_tracker.state = MagicMock()

    monkeypatch.setattr(
        'backend.orchestration.session_orchestrator.OrchestrationServices',
        FakeServices,
    )
    monkeypatch.setattr(
        'backend.orchestration.session_orchestrator.LLMRateGovernor',
        _make_mock,
    )
    monkeypatch.setattr(
        'backend.orchestration.session_orchestrator.MemoryPressureMonitor',
        _make_mock,
    )
    monkeypatch.setattr(
        'backend.orchestration.session_orchestrator.ActionScheduler',
        _make_scheduler,
    )
    monkeypatch.setattr(
        'backend.orchestration.session_orchestrator.SessionOrchestrator._initialize_operation_pipeline',
        _disable_pipeline,
    )
    monkeypatch.setattr(
        'backend.orchestration.session_orchestrator.set_main_event_loop',
        _record_main_loop,
    )

    config = cast(
        OrchestrationConfig,
        SimpleNamespace(
            pending_action_timeout=30.0,
            sid='test-sid',
            event_stream=MagicMock(),
            agent=MagicMock(),
            user_id=None,
            file_store=MagicMock(),
            headless_mode=False,
            conversation_stats=MagicMock(),
            status_callback=None,
            security_analyzer=None,
            initial_state=None,
            iteration_delta=10,
            budget_per_task_delta=1.0,
            replay_events=None,
            agent_to_llm_config={},
            agent_configs={},
            enable_parallel_tool_scheduling=False,
        ),
    )

    SessionOrchestrator(config)
    running_loop = asyncio.get_running_loop()

    assert captured_loops == [running_loop]


def test_default_operation_pipeline_order_is_stable() -> None:
    ctrl = _make_controller()
    ctrl.services.context = MagicMock()

    SessionOrchestrator._initialize_operation_pipeline(ctrl)

    middlewares = ctrl.services.context.initialize_operation_pipeline.call_args.args[0]
    assert [middleware.__class__.__name__ for middleware in middlewares] == [
        'SafetyValidatorMiddleware',
        'BlackboardMiddleware',
        'CircuitBreakerMiddleware',
        'ProgressPolicyMiddleware',
        'CostQuotaMiddleware',
        'ContextWindowMiddleware',
        'RollbackMiddleware',
        'DestructiveCommandMiddleware',
        'PreExecDiffMiddleware',
        'AutoCheckMiddleware',
        'PostEditDiagnosticsMiddleware',
        'SymbolIndexInvalidationMiddleware',
        'FileStateMiddleware',
        'LoggingMiddleware',
        'TelemetryMiddleware',
        'ToolResultValidator',
    ]
    assert ctrl._rollback_middleware.__class__.__name__ == 'RollbackMiddleware'
    assert ctrl._file_state_tracker is middlewares[12].tracker


# ── Service aliasing ────────────────────────────────────────────────


class TestServiceAliasing:
    """Test __getattr__ service alias magic."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl

    def test_action_service_alias(self):
        assert self.ctrl.action_service is self.ctrl.services.action

    def test_pending_action_service_alias(self):
        assert self.ctrl.pending_action_service is self.ctrl.services.pending_action

    def test_autonomy_service_alias(self):
        assert self.ctrl.autonomy_service is self.ctrl.services.autonomy

    def test_iteration_service_alias(self):
        assert self.ctrl.iteration_service is self.ctrl.services.iteration

    def test_lifecycle_service_alias(self):
        assert self.ctrl.lifecycle_service is self.ctrl.services.lifecycle

    def test_recovery_service_alias(self):
        assert self.ctrl.recovery_service is self.ctrl.services.recovery

    def test_retry_service_alias(self):
        assert self.ctrl.retry_service is self.ctrl.services.retry

    def test_state_service_alias(self):
        assert self.ctrl.state_service is self.ctrl.services.state

    def test_iteration_guard_alias(self):
        assert self.ctrl.iteration_guard is self.ctrl.services.iteration_guard

    def test_step_guard_alias(self):
        assert self.ctrl.step_guard is self.ctrl.services.step_guard

    def test_step_prerequisites_alias(self):
        assert self.ctrl.step_prerequisites is self.ctrl.services.step_prerequisites

    def test_event_router_alias(self):
        assert self.ctrl.event_router is self.ctrl.services.event_router

    def test_step_decision_alias(self):
        assert self.ctrl.step_decision is self.ctrl.services.step_decision

    def test_exception_handler_alias(self):
        assert self.ctrl.exception_handler is self.ctrl.services.exception_handler

    def test_action_execution_alias(self):
        assert self.ctrl.action_execution is self.ctrl.services.action_execution

    def test_unknown_attribute_raises(self):
        missing_attr = 'nonexistent_attr_12345'
        with pytest.raises(AttributeError):
            getattr(self.ctrl, missing_attr)

    def test_alias_before_services_set(self):
        """Covers the edge case where services hasn't been set yet."""
        ctrl = _make_controller()
        del ctrl.__dict__['services']
        with pytest.raises(AttributeError):
            _ = ctrl.action_service

    # Explicit property shortcuts
    def test_stuck_service_property(self):
        assert self.ctrl.stuck_service is self.ctrl.services.stuck

    def test_circuit_breaker_service_property(self):
        assert self.ctrl.circuit_breaker_service is self.ctrl.services.circuit_breaker

    def test_observation_service_property(self):
        assert self.ctrl.observation_service is self.ctrl.services.observation

    def test_task_validation_service_property(self):
        assert self.ctrl.task_validation_service is self.ctrl.services.task_validation


# ── Logging ──────────────────────────────────────────────────────────


class TestRepr:
    """Test __repr__."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl

    def test_repr_contains_id(self):
        self.ctrl.services.action.get_pending_action_info.return_value = None
        result = repr(self.ctrl)
        assert 'SessionOrchestrator' in result
        assert 'test-sid' in result

    def test_repr_no_pending_action(self):
        self.ctrl.services.action.get_pending_action_info.return_value = None
        result = repr(self.ctrl)
        assert '<none>' in result

    def test_repr_with_pending_action(self):
        import time

        mock_action = MagicMock()
        mock_action.id = 42
        mock_action.__class__.__name__ = 'CmdRunAction'
        self.ctrl.services.action.get_pending_action_info.return_value = (
            mock_action,
            time.time() - 5.0,
        )
        result = repr(self.ctrl)
        assert 'CmdRunAction' in result


# ── _handle_post_execution ───────────────────────────────────────────


class TestConstants:
    """Test module-level constants exist."""

    def test_traffic_control_reminder(self):
        assert 'resume' in TRAFFIC_CONTROL_REMINDER

    def test_error_action_not_executed_stopped(self):
        assert 'Ctrl+C' in ERROR_ACTION_NOT_EXECUTED_STOPPED
        assert 'cancelled' in ERROR_ACTION_NOT_EXECUTED_STOPPED.lower()

    def test_error_action_not_executed_error(self):
        assert 'Runtime error' in ERROR_ACTION_NOT_EXECUTED_ERROR
        assert 'Ctrl+C' in ERROR_ACTION_NOT_EXECUTED_ERROR
