# pyright: reportAttributeAccessIssue=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false
# mypy: disable-error-code="assignment,attr-defined,method-assign,misc"
"""Tests for SessionOrchestrator — the main agent orchestration controller."""
# pylint: disable=protected-access,too-many-lines

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.core.enums import LifecyclePhase
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import MessageAction
from backend.orchestration.action_scheduler import ActionScheduler
from backend.orchestration.orchestration_config import OrchestrationConfig
from backend.orchestration.session_orchestrator import (
    ERROR_ACTION_NOT_EXECUTED_ERROR,
    ERROR_ACTION_NOT_EXECUTED_STOPPED,
    ERROR_ACTION_NOT_EXECUTED_STOPPED_ID,
    TRAFFIC_CONTROL_REMINDER,
    SessionOrchestrator,
)


class TestLogging:
    """Test log() method."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    @patch('backend.orchestration.mixins.action_mixin.logger')
    def test_log_info(self, mock_logger):
        self.ctrl.log('info', 'Hello')
        mock_logger.info.assert_called_once()

    @patch('backend.orchestration.mixins.action_mixin.logger')
    def test_log_includes_session_id(self, mock_logger):
        self.ctrl.log('debug', 'Testing')
        call_kwargs = mock_logger.debug.call_args
        assert 'session_id' in call_kwargs.kwargs.get('extra', {})

    @patch('backend.orchestration.mixins.action_mixin.logger')
    def test_log_merges_extra(self, mock_logger):
        self.ctrl.log('warning', 'Alert', extra={'custom_key': 'val'})
        call_kwargs = mock_logger.warning.call_args
        extra = call_kwargs.kwargs.get('extra', {})
        assert 'custom_key' in extra
        assert 'session_id' in extra


# ── Step execution ───────────────────────────────────────────────────




class TestLogTaskAudit:
    """Test log_task_audit."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    @pytest.mark.asyncio
    async def test_no_audit_callback(self):
        self.ctrl._audit_callback = None
        # Should not raise
        await self.ctrl.log_task_audit('completed')

    @pytest.mark.asyncio
    async def test_audit_callback_invoked(self):
        callback = MagicMock(return_value=None)
        self.ctrl._audit_callback = callback

        task_mock = MagicMock()
        task_mock.description = 'Test task'
        with patch.object(self.ctrl, '_get_initial_task', return_value=task_mock):
            self.ctrl.state_tracker.state.metrics = MagicMock()
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.prompt_tokens = 100
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.completion_tokens = 50
            self.ctrl.state_tracker.state.metrics.accumulated_cost = 0.05

            await self.ctrl.log_task_audit('completed')

        callback.assert_called_once()
        call_kwargs = callback.call_args.kwargs
        assert call_kwargs['status'] == 'completed'
        assert call_kwargs['tokens_used'] == 150

    @pytest.mark.asyncio
    async def test_audit_callback_async(self):
        callback = AsyncMock(return_value=None)
        self.ctrl._audit_callback = callback

        task_mock = MagicMock()
        task_mock.description = 'Async task'
        with patch.object(self.ctrl, '_get_initial_task', return_value=task_mock):
            self.ctrl.state_tracker.state.metrics = MagicMock()
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.prompt_tokens = 50
            self.ctrl.state_tracker.state.metrics.accumulated_token_usage.completion_tokens = 50
            self.ctrl.state_tracker.state.metrics.accumulated_cost = 0.01

            await self.ctrl.log_task_audit('error', error_message='Failed')

        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_audit_callback_exception_handled(self):
        callback = MagicMock(side_effect=RuntimeError('Audit fail'))
        self.ctrl._audit_callback = callback

        with patch.object(self.ctrl, '_get_initial_task', side_effect=RuntimeError):
            # Should not raise
            await self.ctrl.log_task_audit('error')


# ── Constants ────────────────────────────────────────────────────────




class TestSessionOrchestratorExtendedCoverage:
    """Explicitly target missing lines."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    @pytest.mark.asyncio
    async def test_set_agent_state_to(self):
        """Line 480-484 coverage."""
        self.ctrl.services.state.set_agent_state = AsyncMock()
        await self.ctrl.set_agent_state_to(AgentState.RUNNING)
        self.ctrl.services.state.set_agent_state.assert_awaited_once_with(
            AgentState.RUNNING
        )

    def test_on_event_schedule(self):
        """Line 353 and 357 (indirectly via on_event)."""
        event = MagicMock()
        with patch(
            'backend.orchestration.mixins.step_mixin.run_or_schedule'
        ) as mock_run:
            self.ctrl.on_event(event)
            mock_run.assert_called_once()

    def test_log_step_info(self):
        """Line 509 coverage."""
        self.ctrl.state_tracker.state.get_local_step.return_value = 1
        self.ctrl.state_tracker.state.iteration_flag.current_value = 5
        with patch.object(self.ctrl, 'log') as mock_log:
            self.ctrl._log_step_info()
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_step_early_return_no_action(self):
        """Line 538-541 coverage."""
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl.services.action_execution.get_next_action = AsyncMock(
            return_value=None
        )
        self.ctrl.services.retry.retry_count = 0

        with patch.object(self.ctrl, '_run_control_flags_safely', return_value=True):
            await self.ctrl._step()

        # execute_action should not be called
        self.ctrl.services.action_execution.execute_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_drains_pending(self):
        """Test _can_drain_pending loop in _step (564-570)."""
        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl.services.retry.retry_count = 0

        # 1st action: something. 2nd: something else. 3rd: None.
        a1 = MagicMock()
        a2 = MagicMock()
        self.ctrl.services.action_execution.get_next_action = AsyncMock(
            side_effect=[a1, a2, None]
        )
        self.ctrl.services.action_execution.execute_action = AsyncMock()

        # _can_drain_pending: 1st True, 2nd False
        with (
            patch.object(self.ctrl, '_run_control_flags_safely', return_value=True),
            patch.object(
                type(self.ctrl),
                '_pending_action',
                new_callable=PropertyMock,
                return_value=None,
            ),
            patch.object(
                self.ctrl,
                '_try_parallel_read_batch',
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(self.ctrl, '_can_drain_pending', side_effect=[True, False]),
            patch.object(self.ctrl, '_handle_post_execution', new_callable=AsyncMock),
        ):
            await self.ctrl._step()

        assert self.ctrl.services.action_execution.execute_action.call_count == 2

    @pytest.mark.asyncio
    async def test_step_scheduled_after_non_blocking_action(self):
        """Non-blocking actions must defer the next step instead of losing a wakeup."""
        from backend.core.schemas import AgentState

        self.ctrl.services.step_prerequisites.can_step.return_value = True
        self.ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
        self.ctrl._sync_budget_flag_with_metrics = MagicMock()
        self.ctrl.services.retry.retry_count = 0

        self.ctrl.get_agent_state = MagicMock(return_value=AgentState.RUNNING)
        self.ctrl.services.action_execution.get_next_action = AsyncMock(
            return_value=MagicMock()
        )
        self.ctrl.services.action_execution.execute_action = AsyncMock()
        self.ctrl.schedule_step_soon = MagicMock()

        with (
            patch.object(self.ctrl, '_run_control_flags_safely', return_value=True),
            patch.object(
                type(self.ctrl),
                '_pending_action',
                new_callable=PropertyMock,
                return_value=None,
            ),
            patch.object(
                self.ctrl,
                '_try_parallel_read_batch',
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(self.ctrl, '_can_drain_pending', return_value=False),
            patch.object(self.ctrl, '_handle_post_execution', new_callable=AsyncMock),
        ):
            await self.ctrl._step()

        self.ctrl.schedule_step_soon.assert_called_once()

    @pytest.mark.asyncio
    async def test_parallel_batch_failure_requeues_failed_actions_for_serial_retry(
        self,
    ):
        success_action = SimpleNamespace(
            action='read',
            id=101,
            tool_call_metadata=MagicMock(),
        )
        failed_action = SimpleNamespace(
            action='read',
            id=102,
            tool_call_metadata=MagicMock(),
        )
        overflow_action = SimpleNamespace(
            action='read',
            id=103,
            tool_call_metadata=MagicMock(),
        )
        self.ctrl.config.agent.pending_actions = [
            success_action,
            failed_action,
            overflow_action,
        ]
        self.ctrl.action_scheduler = ActionScheduler(
            enabled=True, max_parallel_batch_size=2
        )

        async def _execute(action):
            if action is failed_action:
                raise RuntimeError('boom')
            return None

        self.ctrl.services.action_execution.execute_action = AsyncMock(
            side_effect=_execute
        )

        with patch.object(
            self.ctrl, '_handle_post_execution', new_callable=AsyncMock
        ) as mock_post:
            executed = await self.ctrl._try_parallel_read_batch()

            assert executed
            assert self.ctrl.config.agent.pending_actions == [
                failed_action,
                overflow_action,
            ]
            assert getattr(
                failed_action, '_retry_serial_after_parallel_failure', False
            )
            assert mock_post.await_count == 1

            self.ctrl.services.action_execution.execute_action.reset_mock()
            second_attempt = await self.ctrl._try_parallel_read_batch()

        assert not second_attempt
        self.ctrl.services.action_execution.execute_action.assert_not_called()

    def test_cleanup_action_context_no_action(self):
        """Line 213-228 coverage for action=None path."""
        self.ctrl._action_contexts_by_object = {}
        self.ctrl._action_contexts_by_event_id = {}

        ctx = MagicMock()
        ctx.action_id = 123
        self.ctrl._action_contexts_by_object[1] = ctx
        self.ctrl._action_contexts_by_event_id[123] = ctx

        self.ctrl._cleanup_action_context(ctx, action=None)
        assert len(self.ctrl._action_contexts_by_object) == 0
        assert len(self.ctrl._action_contexts_by_event_id) == 0

    def test_first_user_message_cached(self):
        """Line 684 coverage (cached return)."""
        mock_msg = MagicMock()
        self.ctrl._cached_first_user_message = mock_msg
        # Use a real list so mock_msg in history returns True
        self.ctrl.state_tracker.state.history = [mock_msg]
        res = self.ctrl._first_user_message()
        assert res == mock_msg

    def test_add_system_message_already_present(self):
        """Line 230-245 coverage (early exit if system message exists)."""
        self.ctrl.state_tracker.state.start_id = 0
        from backend.ledger.action import SystemMessageAction

        sys_msg = SystemMessageAction(content='test')
        self.ctrl.event_stream.search_events = MagicMock(return_value=[sys_msg])

        self.ctrl.agent.get_system_message = MagicMock()
        self.ctrl._add_system_message()
        self.ctrl.agent.get_system_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_invoke_audit_callback_sync(self):
        """Line 715-722 coverage for sync callback."""
        callback = MagicMock()
        await self.ctrl._invoke_audit_callback(callback, x=1)
        callback.assert_called_once_with(x=1)


# ── Step dispatch (cross-thread scheduling) ─────────────────────────




class TestApplyUserDecision:
    """Tests for :meth:`SessionOrchestrator.apply_user_decision`.

    Replaces the previous ``ChangeAgentStateAction(USER_CONFIRMED/REJECTED)``
    event flow that could race with the agent's state.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl

        self.ctrl.services.pending_action = MagicMock()
        self.ctrl.services.context = MagicMock()
        self.ctrl.services.context.emit_event = MagicMock()
        self.ctrl.set_agent_state_to = AsyncMock()
        self.ctrl.step = MagicMock()

    @pytest.mark.asyncio
    async def test_approve_confirms_and_starts_running(self):
        """Approve: sets CONFIRMED, clears pending, emits action,
        transitions to RUNNING, triggers a step.
        """
        from backend.ledger.action import ActionConfirmationStatus

        mock_pending = MagicMock()
        mock_pending.thought = 'I should rm -rf /'
        mock_pending._id = 'action-1'
        self.ctrl.services.pending_action.get.return_value = mock_pending

        await self.ctrl.apply_user_decision(approved=True)

        # confirmation_state is set
        assert mock_pending.confirmation_state == ActionConfirmationStatus.CONFIRMED
        # thought is cleared (so the agent doesn't re-display its plan)
        assert mock_pending.thought == ''
        # action id is cleared (so the action is re-executable)
        assert mock_pending._id is None
        # outstanding row cleared while stream id was still valid
        self.ctrl.services.pending_action.clear_for_action.assert_called_once_with(
            mock_pending
        )
        # action is re-emitted as AGENT
        self.ctrl.services.context.emit_event.assert_called_once_with(
            mock_pending, EventSource.AGENT
        )
        # state transitions to RUNNING
        self.ctrl.set_agent_state_to.assert_awaited_once_with(AgentState.RUNNING)
        # step is triggered
        self.ctrl.step.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_rejects_and_awaits_input(self):
        """Reject: sets REJECTED, clears pending, emits action,
        transitions to AWAITING_USER_INPUT, triggers a step.
        """
        from backend.ledger.action import ActionConfirmationStatus

        mock_pending = MagicMock()
        mock_pending.thought = 'I should rm -rf /'
        mock_pending._id = 'action-2'
        self.ctrl.services.pending_action.get.return_value = mock_pending

        await self.ctrl.apply_user_decision(approved=False)

        assert mock_pending.confirmation_state == ActionConfirmationStatus.REJECTED
        self.ctrl.services.pending_action.clear_for_action.assert_called_once_with(
            mock_pending
        )
        self.ctrl.services.context.emit_event.assert_called_once_with(
            mock_pending, EventSource.AGENT
        )
        self.ctrl.set_agent_state_to.assert_awaited_once_with(
            AgentState.AWAITING_USER_INPUT
        )
        self.ctrl.step.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_pending_action_is_a_noop_when_not_awaiting_confirmation(self):
        """No pending action outside the confirmation gate is a no-op."""
        self.ctrl.services.pending_action.get.return_value = None
        self.ctrl.get_agent_state = MagicMock(return_value=AgentState.RUNNING)

        await self.ctrl.apply_user_decision(approved=True)

        self.ctrl.services.pending_action.clear_for_action.assert_not_called()
        self.ctrl.services.context.emit_event.assert_not_called()
        self.ctrl.set_agent_state_to.assert_not_awaited()
        self.ctrl.step.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_confirmation_gate_released_without_pending(self):
        """Orphan AWAITING_USER_CONFIRMATION without pending recovers to RUNNING."""
        self.ctrl.services.pending_action.get.return_value = None
        self.ctrl.get_agent_state = MagicMock(
            return_value=AgentState.AWAITING_USER_CONFIRMATION
        )

        await self.ctrl.apply_user_decision(approved=True)

        self.ctrl.set_agent_state_to.assert_awaited_once_with(AgentState.RUNNING)
        self.ctrl.services.context.emit_event.assert_not_called()
        self.ctrl.step.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_for_action_runs_before_id_is_wiped(self):
        """Pre-confirmation stream id must be cleared before ``_id`` is reset."""
        mock_pending = MagicMock()
        mock_pending.thought = ''
        mock_pending._id = 248
        captured_id_at_clear: list[object] = []

        def _capture_clear(action):
            captured_id_at_clear.append(getattr(action, '_id', None))

        self.ctrl.services.pending_action.get.return_value = mock_pending
        self.ctrl.services.pending_action.clear_for_action.side_effect = _capture_clear

        await self.ctrl.apply_user_decision(approved=True)

        assert captured_id_at_clear == [248]
        assert mock_pending._id is None

    @pytest.mark.asyncio
    async def test_pending_action_without_thought_attribute(self):
        """Pending actions that don't have a ``thought`` attribute are handled."""
        mock_pending = MagicMock(spec=['_id', 'confirmation_state'])
        mock_pending._id = 'action-3'
        self.ctrl.services.pending_action.get.return_value = mock_pending

        await self.ctrl.apply_user_decision(approved=True)

        self.ctrl.services.pending_action.clear_for_action.assert_called_once_with(
            mock_pending
        )
        self.ctrl.services.context.emit_event.assert_called_once_with(
            mock_pending, EventSource.AGENT
        )
