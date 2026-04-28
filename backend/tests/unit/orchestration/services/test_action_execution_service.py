"""Tests for ActionExecutionService."""

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoActionError,
    LLMResponseError,
)
from backend.inference.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    RateLimitError,
)
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    FileEditAction,
    MCPAction,
    NullAction,
)
from backend.ledger.action.agent import CondensationRequestAction, PlaybookFinishAction
from backend.orchestration.services.action_execution_service import (
    ActionExecutionService,
)


class TestActionExecutionService(unittest.IsolatedAsyncioTestCase):
    """Test ActionExecutionService action execution logic."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.mock_context.agent = MagicMock()
        self.mock_context.agent.step = MagicMock()
        self.mock_context.agent.config = MagicMock()
        self.mock_context.agent.config.enable_history_truncation = False
        self.mock_context.state = MagicMock()
        self.mock_context.event_stream = MagicMock()
        self.mock_context.confirmation_service = None
        self.mock_context.operation_pipeline = None
        self.mock_context.tool_pipeline = None
        self.mock_context.iteration_service = MagicMock()
        self.mock_context.iteration_service.apply_dynamic_iterations = AsyncMock()
        self.mock_context.telemetry_service = MagicMock()
        self.mock_context.register_action_context = MagicMock()
        self.mock_context.run_action = AsyncMock()

        self.service = ActionExecutionService(self.mock_context)

    async def test_get_next_action_from_agent(self):
        """Test get_next_action retrieves action from agent."""
        mock_action = MagicMock(spec=Action)
        self.mock_context.agent.step.return_value = mock_action

        result = await self.service.get_next_action()

        # Should return action with AGENT source
        self.assertEqual(result, mock_action)
        self.assertEqual(mock_action.source, EventSource.AGENT)
        self.mock_context.agent.step.assert_called_once_with(self.mock_context.state)

    async def test_get_next_action_from_confirmation_service(self):
        """Test get_next_action uses confirmation only during trajectory replay."""
        mock_action = MagicMock(spec=Action)

        mock_confirmation = MagicMock()
        mock_confirmation.get_next_action.return_value = mock_action
        self.mock_context.confirmation_service = mock_confirmation
        mock_controller = MagicMock()
        mock_controller._replay_manager.should_replay.return_value = True
        self.mock_context.get_controller.return_value = mock_controller

        result = await self.service.get_next_action()

        # Should use confirmation service
        self.assertEqual(result, mock_action)
        mock_confirmation.get_next_action.assert_called_once()
        self.mock_context.agent.step.assert_not_called()

    async def test_get_next_action_malformed_action_error(self):
        """Test get_next_action handles LLMMalformedActionError."""
        self.mock_context.agent.step.side_effect = LLMMalformedActionError('Bad action')

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)
        self.mock_context.event_stream.add_event.assert_called_once()

    async def test_get_next_action_no_action_error(self):
        """Test get_next_action handles LLMNoActionError."""
        self.mock_context.agent.step.side_effect = LLMNoActionError('No action')

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)
        self.mock_context.event_stream.add_event.assert_called_once()

    async def test_get_next_action_response_error(self):
        """Test get_next_action handles LLMResponseError."""
        self.mock_context.agent.step.side_effect = LLMResponseError('Response error')

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)

    async def test_get_next_action_function_validation_error(self):
        """Test get_next_action handles FunctionCallValidationError."""
        self.mock_context.agent.step.side_effect = FunctionCallValidationError(
            'Invalid'
        )

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)

    async def test_get_next_action_function_not_exists_error(self):
        """Test get_next_action handles FunctionCallNotExistsError."""
        self.mock_context.agent.step.side_effect = FunctionCallNotExistsError(
            'Not found'
        )

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)

    async def test_get_next_action_context_window_exceeded(self):
        """Test get_next_action handles context window exceeded."""
        self.mock_context.agent.step.side_effect = ContextWindowExceededError(
            'Too large'
        )
        self.mock_context.agent.config.enable_history_truncation = True

        with patch.object(
            self.service, '_handle_context_window_error', new_callable=AsyncMock
        ) as mock_handle:
            mock_handle.return_value = None
            await self.service.get_next_action()

        # Should delegate to context window handler
        mock_handle.assert_called_once()

    async def test_get_next_action_api_connection_error_raises(self):
        """Test get_next_action raises APIConnectionError."""
        self.mock_context.agent.step.side_effect = APIConnectionError(
            'Connection failed'
        )

        with self.assertRaises(APIConnectionError):
            await self.service.get_next_action()

    async def test_get_next_action_authentication_error_raises(self):
        """Test get_next_action raises AuthenticationError."""
        self.mock_context.agent.step.side_effect = AuthenticationError('Auth failed')

        with self.assertRaises(AuthenticationError):
            await self.service.get_next_action()

    async def test_get_next_action_rate_limit_error_raises(self):
        """Test get_next_action raises RateLimitError."""
        self.mock_context.agent.step.side_effect = RateLimitError('Rate limited')

        with self.assertRaises(RateLimitError):
            await self.service.get_next_action()

    async def test_get_next_action_recovers_first_round_then_pauses(self):
        """Null-action loop uses two-round recovery before pausing.

        Round 1 (5 consecutive NullActions): emits NULL_ACTION_LOOP_RECOVERY and
        keeps the loop running — no pause, no AWAITING_USER_INPUT.
        Round 2 (another 5): emits NULL_ACTION_LOOP and pauses.
        """
        from backend.core.schemas import AgentState

        nulls = [NullAction() for _ in range(10)]
        self.mock_context.agent.astep = AsyncMock(side_effect=nulls)
        mock_controller = MagicMock()
        mock_controller.get_agent_state.return_value = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        self.mock_context.get_controller.return_value = mock_controller

        results: list[Any] = []
        for _ in range(10):
            results.append(await self.service.get_next_action())

        # First 9 calls return NullAction (4 pass-through + 1 recovery at round-1
        # threshold + 4 more pass-through), 10th returns None (round-2 pause).
        self.assertEqual(results.count(None), 1)
        self.assertIsNone(results[-1])

        # Two observations total: first is recovery, second is the hard pause.
        self.assertEqual(self.mock_context.event_stream.add_event.call_count, 2)
        first_obs = self.mock_context.event_stream.add_event.call_args_list[0][0][0]
        second_obs = self.mock_context.event_stream.add_event.call_args_list[1][0][0]
        self.assertEqual(first_obs.error_id, 'NULL_ACTION_LOOP_RECOVERY')
        self.assertEqual(second_obs.error_id, 'NULL_ACTION_LOOP')

        # Only pauses after the second round is exhausted.
        mock_controller.set_agent_state_to.assert_awaited_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    async def test_get_next_action_pauses_after_repeated_null_actions(self):
        """Backward-compat alias: first recovery round emits recovery obs, not a pause."""
        from backend.core.schemas import AgentState

        self.mock_context.agent.astep = AsyncMock(
            side_effect=[
                NullAction(),
                NullAction(),
                NullAction(),
                NullAction(),
                NullAction(),
            ]
        )
        mock_controller = MagicMock()
        mock_controller.get_agent_state.return_value = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        self.mock_context.get_controller.return_value = mock_controller

        for _ in range(5):
            await self.service.get_next_action()

        # After 5 nulls (round 1) a recovery observation is emitted but the agent
        # is NOT paused — set_agent_state_to should NOT have been called.
        self.assertEqual(self.mock_context.event_stream.add_event.call_count, 1)
        obs = self.mock_context.event_stream.add_event.call_args[0][0]
        self.assertEqual(obs.error_id, 'NULL_ACTION_LOOP_RECOVERY')
        mock_controller.set_agent_state_to.assert_not_awaited()

    async def test_get_next_action_resets_null_streak_after_real_action(self):
        """A real action should clear the null-action streak."""
        real_action = MagicMock(spec=Action)
        self.mock_context.agent.astep = AsyncMock(
            side_effect=[
                NullAction(),
                real_action,
                NullAction(),
                NullAction(),
            ]
        )

        first = await self.service.get_next_action()
        second = await self.service.get_next_action()
        third = await self.service.get_next_action()
        fourth = await self.service.get_next_action()

        self.assertIsInstance(first, NullAction)
        self.assertEqual(second, real_action)
        self.assertIsInstance(third, NullAction)
        self.assertIsInstance(fourth, NullAction)
        self.mock_context.event_stream.add_event.assert_not_called()

    async def test_get_next_action_preserves_recovery_round_after_real_action(self):
        """A single real action should not buy an extra null-loop recovery round."""
        from backend.core.schemas import AgentState

        real_action = MagicMock(spec=Action)
        self.mock_context.agent.astep = AsyncMock(
            side_effect=[
                *[NullAction() for _ in range(5)],
                real_action,
                *[NullAction() for _ in range(5)],
            ]
        )
        mock_controller = MagicMock()
        mock_controller.get_agent_state.return_value = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        self.mock_context.get_controller.return_value = mock_controller

        results: list[Any] = []
        for _ in range(11):
            results.append(await self.service.get_next_action())

        self.assertEqual(results[5], real_action)
        self.assertIsNone(results[-1])
        self.assertEqual(self.mock_context.event_stream.add_event.call_count, 2)

        first_obs = self.mock_context.event_stream.add_event.call_args_list[0][0][0]
        second_obs = self.mock_context.event_stream.add_event.call_args_list[1][0][0]
        self.assertEqual(first_obs.error_id, 'NULL_ACTION_LOOP_RECOVERY')
        self.assertEqual(second_obs.error_id, 'NULL_ACTION_LOOP')
        mock_controller.set_agent_state_to.assert_awaited_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    async def test_execute_action_runnable_with_pipeline(self):
        """Test execute_action processes runnable action through pipeline."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True

        mock_ctx = MagicMock()
        mock_ctx.blocked = False

        mock_pipeline = MagicMock()
        mock_pipeline.create_context = MagicMock(return_value=mock_ctx)
        self.mock_context.operation_pipeline = mock_pipeline

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service.execute_action(mock_action)

        # Should create context
        mock_pipeline.create_context.assert_called_once_with(
            mock_action, self.mock_context.state
        )
        self.mock_context.register_action_context.assert_called_once_with(
            mock_action, mock_ctx
        )

        # Should apply dynamic iterations
        self.mock_context.iteration_service.apply_dynamic_iterations.assert_called_once_with(
            mock_ctx
        )

        # Should run action
        self.mock_context.run_action.assert_called_once_with(mock_action, mock_ctx)

    async def test_execute_action_non_runnable(self):
        """Test execute_action processes non-runnable action."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service.execute_action(mock_action)

        # Should run action without pipeline
        self.mock_context.run_action.assert_called_once_with(mock_action, None)

    async def test_execute_action_no_pipeline(self):
        """Test execute_action handles missing pipeline."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True

        self.mock_context.operation_pipeline = None

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service.execute_action(mock_action)

        # Should run action without pipeline processing
        self.mock_context.run_action.assert_called_once()

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_execute_action_plugin_hook(self, mock_get_registry: MagicMock):
        """Test execute_action fires plugin pre-action hook."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(return_value=mock_action)
        mock_get_registry.return_value = mock_registry

        await self.service.execute_action(mock_action)

        # Should dispatch to plugin
        mock_registry.dispatch_action_pre.assert_called_once_with(mock_action)

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_execute_action_plugin_exception(self, mock_get_registry: MagicMock):
        """Test execute_action handles plugin exceptions gracefully."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(
            side_effect=RuntimeError('Plugin error')
        )
        mock_get_registry.return_value = mock_registry

        # Should not raise exception
        await self.service.execute_action(mock_action)

        # Should still run action
        self.mock_context.run_action.assert_called_once()

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_execute_action_blocks_write_until_fresh_verification(
        self, mock_get_registry: MagicMock
    ):
        state = MagicMock()
        state.extra_data = {
            '__step_guard_verification_required': {
                'paths': ['backend/context/schemas.py'],
                'observed_failure': 'FAILED: backend/context/schemas.py is out of sync',
            }
        }
        state.set_planning_directive = MagicMock()
        self.mock_context.state = state

        action = FileEditAction(
            path='backend/context/schemas.py',
            command='replace_text',
            old_str='old',
            new_str='new',
        )
        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(return_value=action)
        mock_get_registry.return_value = mock_registry

        await self.service.execute_action(action)

        self.mock_context.run_action.assert_not_called()
        self.mock_context.event_stream.add_event.assert_called_once()
        blocked_obs = self.mock_context.event_stream.add_event.call_args.args[0]
        self.assertEqual(blocked_obs.error_id, 'VERIFICATION_REQUIRED')
        # GuardBus XOR rule: observation emitted → planning_directive NOT also set.
        state.set_planning_directive.assert_not_called()

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_execute_action_allows_grounding_view_to_clear_requirement(
        self, mock_get_registry: MagicMock
    ):
        state = MagicMock()
        state.extra_data = {
            '__step_guard_verification_required': {
                'paths': ['backend/context/schemas.py'],
                'observed_failure': 'FAILED: backend/context/schemas.py is out of sync',
            }
        }
        state.set_extra = MagicMock()
        self.mock_context.state = state

        view_action = FileEditAction(
            path='backend/context/schemas.py', command='read_file'
        )
        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(return_value=view_action)
        mock_get_registry.return_value = mock_registry

        await self.service.execute_action(view_action)

        state.set_extra.assert_called_once_with(
            '__step_guard_verification_required',
            None,
            source='ActionExecutionService',
        )
        self.mock_context.run_action.assert_called_once_with(view_action, None)

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_execute_action_blocks_mutating_mcp_tool_until_grounded(
        self, mock_get_registry: MagicMock
    ):
        state = MagicMock()
        state.extra_data = {
            '__step_guard_verification_required': {
                'paths': ['backend/context/schemas.py'],
                'observed_failure': 'FAILED: backend/context/schemas.py is out of sync',
            }
        }
        self.mock_context.state = state

        action = MCPAction(name='apply_patch', arguments={'input': '*** Begin Patch'})
        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(return_value=action)
        mock_get_registry.return_value = mock_registry

        await self.service.execute_action(action)

        self.mock_context.run_action.assert_not_called()
        blocked_obs = self.mock_context.event_stream.add_event.call_args.args[0]
        self.assertEqual(blocked_obs.error_id, 'VERIFICATION_REQUIRED')

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_execute_action_blocks_finish_until_grounded(self, mock_get_registry: MagicMock):
        state = MagicMock()
        state.extra_data = {
            '__step_guard_verification_required': {
                'paths': ['backend/context/schemas.py'],
                'observed_failure': 'FAILED: backend/context/schemas.py is out of sync',
            }
        }
        self.mock_context.state = state

        action = PlaybookFinishAction(final_thought='done')
        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(return_value=action)
        mock_get_registry.return_value = mock_registry

        await self.service.execute_action(action)

        self.mock_context.run_action.assert_not_called()
        blocked_obs = self.mock_context.event_stream.add_event.call_args.args[0]
        self.assertEqual(blocked_obs.error_id, 'VERIFICATION_REQUIRED')

    @patch(
        'backend.orchestration.services.action_execution_service.is_context_window_error'
    )
    async def test_handle_context_window_error_with_truncation(self, mock_is_ctx_error: MagicMock):
        """Test _handle_context_window_error emits condensation request."""
        exc = ContextWindowExceededError('Context too large')
        mock_is_ctx_error.return_value = True
        self.mock_context.agent.config.enable_history_truncation = True

        result = await self.service._handle_context_window_error(exc)  # type: ignore[reportPrivateUsage]

        # Should emit condensation request
        self.assertIsNone(result)
        self.mock_context.event_stream.add_event.assert_called_once()

        # Check for CondensationRequestAction
        call_args = self.mock_context.event_stream.add_event.call_args[0]
        self.assertIsInstance(call_args[0], CondensationRequestAction)

    @patch(
        'backend.orchestration.services.action_execution_service.is_context_window_error'
    )
    async def test_handle_context_window_error_without_truncation(
        self, mock_is_ctx_error: MagicMock
    ):
        """Test _handle_context_window_error raises when truncation disabled."""
        exc = ContextWindowExceededError('Context too large')
        mock_is_ctx_error.return_value = True
        self.mock_context.agent.config.enable_history_truncation = False

        with self.assertRaises(LLMContextWindowExceedError):
            await self.service._handle_context_window_error(exc)  # type: ignore[reportPrivateUsage]

    @patch(
        'backend.orchestration.services.action_execution_service.is_context_window_error'
    )
    async def test_handle_context_window_error_not_context_window(
        self, mock_is_ctx_error: MagicMock
    ):
        """Test _handle_context_window_error re-raises non-context-window errors."""
        exc = BadRequestError('Bad request')
        mock_is_ctx_error.return_value = False

        with self.assertRaises(BadRequestError):
            await self.service._handle_context_window_error(exc)  # type: ignore[reportPrivateUsage]

    # ------------------------------------------------------------------ #
    # NullActionReason / sentinel bypass tests
    # ------------------------------------------------------------------ #

    async def test_null_action_reason_field_defaults_to_empty(self):
        """NullAction() must have reason='' by default (backward-compatible)."""
        action = NullAction()
        self.assertEqual(action.reason, '')

    async def test_null_action_reason_field_stores_value(self):
        """NullAction(reason=...) stores the provided reason."""
        from backend.ledger.action.empty import NullActionReason

        action = NullAction(reason=NullActionReason.SENTINEL)
        self.assertEqual(action.reason, NullActionReason.SENTINEL)

    async def test_sentinel_null_action_bypasses_consecutive_counter(self):
        """SENTINEL NullActions must never increment the consecutive-null counter.

        20 consecutive SENTINEL NullActions must pass through without triggering
        the NULL_ACTION_LOOP_RECOVERY circuit breaker.
        """
        from backend.ledger.action.empty import NullActionReason

        sentinel = NullAction(reason=NullActionReason.SENTINEL)
        self.mock_context.agent.astep = AsyncMock(return_value=sentinel)

        for _ in range(20):
            result = await self.service.get_next_action()
            self.assertIsNotNone(result)

        # No error observations should have been emitted
        self.mock_context.event_stream.add_event.assert_not_called()

    async def test_sentinel_null_action_counter_stays_zero(self):
        """The _consecutive_null_actions counter stays at 0 for SENTINEL actions."""
        from backend.ledger.action.empty import NullActionReason

        sentinel = NullAction(reason=NullActionReason.SENTINEL)
        self.mock_context.agent.astep = AsyncMock(return_value=sentinel)

        for _ in range(10):
            await self.service.get_next_action()

        self.assertEqual(self.service._consecutive_null_actions, 0)

    async def test_untagged_null_action_still_counts_toward_breaker(self):
        """NullAction with no reason tag behaves as before: triggers recovery at count 5."""
        from backend.core.schemas import AgentState

        mock_controller = MagicMock()
        mock_controller.get_agent_state.return_value = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        self.mock_context.get_controller.return_value = mock_controller

        self.mock_context.agent.astep = AsyncMock(
            side_effect=[NullAction() for _ in range(5)]
        )

        for _ in range(5):
            await self.service.get_next_action()

        # Exactly one recovery observation after 5 untagged NullActions
        self.assertEqual(self.mock_context.event_stream.add_event.call_count, 1)
        obs = self.mock_context.event_stream.add_event.call_args[0][0]
        self.assertEqual(obs.error_id, 'NULL_ACTION_LOOP_RECOVERY')

    async def test_mixed_sentinel_and_real_null_actions(self):
        """SENTINEL NullActions interleaved with untagged ones must not dilute the counter.

        5 untagged NullActions should trigger recovery regardless of how many
        SENTINEL NullActions appear between them.
        """
        from backend.core.schemas import AgentState
        from backend.ledger.action.empty import NullActionReason

        mock_controller = MagicMock()
        mock_controller.get_agent_state.return_value = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        self.mock_context.get_controller.return_value = mock_controller

        sentinel = NullAction(reason=NullActionReason.SENTINEL)
        untagged = NullAction()
        # 5 untagged with SENTINEL noise between them
        actions = [untagged, sentinel, untagged, sentinel, untagged, sentinel, untagged, untagged]
        self.mock_context.agent.astep = AsyncMock(side_effect=actions)

        results = []
        for _ in range(len(actions)):
            results.append(await self.service.get_next_action())

        # Recovery fires after the 5th untagged NullAction
        self.assertEqual(self.mock_context.event_stream.add_event.call_count, 1)
        obs = self.mock_context.event_stream.add_event.call_args[0][0]
        self.assertEqual(obs.error_id, 'NULL_ACTION_LOOP_RECOVERY')


if __name__ == '__main__':
    unittest.main()
