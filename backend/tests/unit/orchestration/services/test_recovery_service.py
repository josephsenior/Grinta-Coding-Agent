"""Tests for RecoveryService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.errors import LLMNoResponseError
from backend.core.schemas import AgentState
from backend.inference.exceptions import (
    APIConnectionError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from backend.ledger.observation import ErrorObservation
from backend.orchestration.services.recovery_service import RecoveryService


@pytest.fixture()
def mock_context():
    ctx = MagicMock()
    ctx.get_controller.return_value = MagicMock()
    ctx.discard_invocation_context_for_action = MagicMock()
    ctx.emit_event = MagicMock()
    ctx.set_agent_state = AsyncMock()
    ctx.trigger_step = MagicMock()
    return ctx


@pytest.fixture()
def ctrl(mock_context):
    c = mock_context.get_controller.return_value
    c.id = 'sid-1'
    c.circuit_breaker_service = MagicMock()
    c.pending_action_service = MagicMock()
    c.pending_action_service.get.return_value = None
    c.retry_service = MagicMock()
    c.retry_service.schedule_retry_after_failure = AsyncMock(return_value=False)
    c.get_agent_state = MagicMock(return_value=AgentState.RUNNING)
    c.state = MagicMock()
    c.state.extra_data = {}
    return c


class TestRecoveryService:
    @pytest.mark.asyncio
    async def test_emits_error_and_schedules_retry_on_timeout(self, mock_context, ctrl):
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(Timeout('slow'))

        ctrl.circuit_breaker_service.record_error.assert_not_called()
        mock_context.emit_event.assert_called_once()
        err_obs, source = mock_context.emit_event.call_args[0]
        assert isinstance(err_obs, ErrorObservation)
        assert err_obs.error_id == 'LLM_TIMEOUT'
        assert 'Timeout' in err_obs.content
        assert err_obs.notify_ui_only is True
        ctrl.retry_service.schedule_retry_after_failure.assert_awaited_once()
        mock_context.set_agent_state.assert_awaited_once_with(AgentState.RATE_LIMITED)

    @pytest.mark.asyncio
    async def test_timeout_without_retry_queue_returns_to_user_input(
        self, mock_context, ctrl
    ):
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=False)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(Timeout('slow'))

        err_obs = mock_context.emit_event.call_args[0][0]
        assert err_obs.notify_ui_only is True
        ctrl.retry_service.schedule_retry_after_failure.assert_awaited_once()
        mock_context.set_agent_state.assert_awaited_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    @pytest.mark.asyncio
    async def test_clears_pending_and_discards_context(self, mock_context, ctrl):
        pending = MagicMock()
        pending.id = 7
        ctrl.pending_action_service.get.return_value = pending

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RuntimeError('x'))

        mock_context.discard_invocation_context_for_action.assert_called_once_with(
            pending
        )
        ctrl.pending_action_service.set.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_retry_scheduled_still_transitions_to_awaiting_input(
        self, mock_context, ctrl
    ):
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RateLimitError('rate limited'))

        ctrl.retry_service.schedule_retry_after_failure.assert_awaited_once()
        mock_context.set_agent_state.assert_awaited_once_with(AgentState.RATE_LIMITED)

    @pytest.mark.asyncio
    async def test_rate_limit_error_message_is_compact(self, mock_context, ctrl):
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(
            RateLimitError(
                'Rate limit reached. Upgrade to the next tier for more requests: https://example.com/pricing'
            )
        )

        err_obs = mock_context.emit_event.call_args[0][0]
        assert 'Rate limit' in err_obs.content
        assert 'https://example.com/pricing' not in err_obs.content
        assert err_obs.notify_ui_only is True

    @pytest.mark.asyncio
    async def test_service_unavailable_sets_notify_ui_only(self, mock_context, ctrl):
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(ServiceUnavailableError('unavailable'))

        err_obs = mock_context.emit_event.call_args[0][0]
        assert err_obs.notify_ui_only is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'exc',
        [
            APIConnectionError('connection reset'),
            InternalServerError('upstream 500'),
            LLMNoResponseError('empty completion'),
        ],
    )
    async def test_transient_llm_infra_sets_notify_ui_only(
        self, mock_context, ctrl, exc
    ):
        """Matches ``LLM_RETRY_EXCEPTIONS`` infra types after inner retries."""
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)
        svc = RecoveryService(mock_context)
        await svc.react_to_exception(exc)

        err_obs = mock_context.emit_event.call_args[0][0]
        assert err_obs.notify_ui_only is True
        assert 'Transient provider or network issue' in err_obs.content
        ctrl.retry_service.schedule_retry_after_failure.assert_awaited_once_with(exc)
        mock_context.set_agent_state.assert_awaited_once_with(AgentState.RATE_LIMITED)

    @pytest.mark.asyncio
    async def test_rate_limit_does_not_pollute_agent_context(self, mock_context, ctrl):
        """Silent-rate-limit policy: transient 429s must NOT add an
        ``AgentThinkObservation`` to the event stream, and the compact
        ``ErrorObservation`` uses ``notify_ui_only`` so it is omitted from
        LLM message assembly. The inner Tenacity loop + outer retry queue
        handle recovery autonomously.
        """
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)
        ctrl.event_stream = MagicMock()
        ctrl.event_stream.add_event = MagicMock()

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RateLimitError('rate limited'))

        err_obs = mock_context.emit_event.call_args[0][0]
        assert err_obs.notify_ui_only is True

        # No AgentThinkObservation may have been pushed by the recovery service.
        for call in ctrl.event_stream.add_event.call_args_list:
            event = call.args[0] if call.args else call.kwargs.get('event')
            assert type(event).__name__ != 'AgentThinkObservation', (
                'Rate-limit handling must be silent in the agent context; '
                f'got AgentThinkObservation: {event!r}'
            )

    @pytest.mark.asyncio
    async def test_rate_limit_after_user_stop_skips_state_transition(
        self, mock_context, ctrl
    ):
        ctrl.get_agent_state.return_value = AgentState.STOPPED
        ctrl.retry_service.schedule_retry_after_failure = AsyncMock(return_value=True)

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RateLimitError('late 429'))

        mock_context.set_agent_state.assert_not_awaited()
        ctrl.retry_service.schedule_retry_after_failure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authentication_sets_notify_ui_only(self, mock_context, ctrl):
        svc = RecoveryService(mock_context)
        await svc.react_to_exception(AuthenticationError('bad key'))

        err_obs = mock_context.emit_event.call_args[0][0]
        assert err_obs.notify_ui_only is True

    @pytest.mark.asyncio
    async def test_timeout_with_recent_mcp_validation_error_sets_directive(
        self, mock_context, ctrl
    ):
        state = MagicMock()
        state.turn_signals = MagicMock(planning_directive=None)
        state.history = [
            MagicMock(
                observation='mcp',
                content='{"error_code":"MCP_TOOL_VALIDATION_ERROR","error":"MCP error -32602"}',
            )
        ]
        state.set_planning_directive = MagicMock()
        ctrl.state = state

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(Timeout('slow'))

        state.set_planning_directive.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_without_recent_mcp_validation_error_does_not_set_directive(
        self, mock_context, ctrl
    ):
        state = MagicMock()
        state.turn_signals = MagicMock(planning_directive=None)
        state.history = [
            MagicMock(
                observation='mcp',
                content='{"error_code":"MCP_TOOL_ERROR","error":"random server error"}',
            )
        ]
        state.set_planning_directive = MagicMock()
        ctrl.state = state

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(Timeout('slow'))

        state.set_planning_directive.assert_not_called()


# ---------------------------------------------------------------------------
# Task reconciliation directive after survivable errors
# ---------------------------------------------------------------------------


class TestTaskReconciliationDirective:
    """RecoveryService should inject a planning directive when doing steps exist."""

    @pytest.fixture()
    def state_with_doing_step(self):
        step = MagicMock(status='doing', id='2')
        plan = MagicMock(steps=[step])
        state = MagicMock()
        state.turn_signals = MagicMock(planning_directive=None)
        state.plan = plan
        state.set_planning_directive = MagicMock()
        state.history = []
        state.extra_data = {}
        return state

    @pytest.mark.asyncio
    async def test_survivable_error_with_doing_step_injects_directive(
        self,
        mock_context,
        ctrl,
        state_with_doing_step,
    ):
        ctrl.state = state_with_doing_step
        ctrl.get_agent_state.return_value = AgentState.RUNNING

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RuntimeError('tool failed'))

        state_with_doing_step.set_planning_directive.assert_called_once()
        directive = state_with_doing_step.set_planning_directive.call_args[0][0]
        assert 'task_tracker' in directive
        assert 'doing' in directive

    @pytest.mark.asyncio
    async def test_survivable_error_without_doing_step_no_directive(
        self,
        mock_context,
        ctrl,
    ):
        step = MagicMock(status='todo', id='1')
        plan = MagicMock(steps=[step])
        state = MagicMock()
        state.turn_signals = MagicMock(planning_directive=None)
        state.plan = plan
        state.set_planning_directive = MagicMock()
        state.history = []
        state.extra_data = {}
        ctrl.state = state
        ctrl.get_agent_state.return_value = AgentState.RUNNING

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RuntimeError('tool failed'))

        state.set_planning_directive.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_directive_when_existing_directive_present(
        self,
        mock_context,
        ctrl,
        state_with_doing_step,
    ):
        state_with_doing_step.turn_signals.planning_directive = 'already set'
        ctrl.state = state_with_doing_step
        ctrl.get_agent_state.return_value = AgentState.RUNNING

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RuntimeError('tool failed'))

        state_with_doing_step.set_planning_directive.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_directive_when_no_plan_exists(
        self,
        mock_context,
        ctrl,
    ):
        state = MagicMock()
        state.turn_signals = MagicMock(planning_directive=None)
        state.plan = None
        state.set_planning_directive = MagicMock()
        state.history = []
        state.extra_data = {}
        ctrl.state = state
        ctrl.get_agent_state.return_value = AgentState.RUNNING

        svc = RecoveryService(mock_context)
        await svc.react_to_exception(RuntimeError('tool failed'))

        state.set_planning_directive.assert_not_called()
