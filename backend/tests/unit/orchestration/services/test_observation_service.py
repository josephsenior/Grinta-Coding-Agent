"""Tests for ObservationService."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ledger.observation import ErrorObservation, Observation
from backend.orchestration.services.observation_service import (
    ObservationService,
    transition_agent_state_logic,
)
from backend.orchestration.state.state import AgentState


class TestObservationService(unittest.IsolatedAsyncioTestCase):
    """Test ObservationService observation handling."""

    def setUp(self):
        """Create mock dependencies for testing."""
        self.mock_context = MagicMock()
        self.mock_controller = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller

        # Setup confirmation service with async method
        self.mock_confirmation_service = MagicMock()
        self.mock_confirmation_service.handle_observation_for_pending_action = (
            AsyncMock()
        )
        self.mock_controller.confirmation_service = self.mock_confirmation_service

        self.mock_pending_service = MagicMock()
        self.mock_pending_service.peek_for_cause = MagicMock(return_value=None)
        self.mock_pending_service.pop_for_cause = MagicMock(return_value=None)
        self.mock_pending_service.has_outstanding_for_cause = MagicMock(
            return_value=False
        )

        self.service = ObservationService(self.mock_context, self.mock_pending_service)

    @patch.dict('os.environ', {'LOG_ALL_EVENTS': '1'})
    async def test_handle_observation_log_all_events(self):
        """Test handle_observation logs at info level when LOG_ALL_EVENTS=1."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = None
        mock_observation.content = 'Test observation'

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 1000
        self.mock_controller.log = MagicMock()

        self.mock_pending_service.get.return_value = None

        await self.service.handle_observation(mock_observation)

        # Should log at info level
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], 'info')

    @patch.dict('os.environ', {}, clear=True)
    async def test_handle_observation_default_log_level(self):
        """Test handle_observation logs at debug level by default."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = None
        mock_observation.content = 'Test'

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 500
        self.mock_controller.log = MagicMock()

        self.mock_pending_service.get.return_value = None

        await self.service.handle_observation(mock_observation)

        # Should log at debug level
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], 'debug')

    @patch('backend.orchestration.services.observation_service.truncate_content')
    async def test_prepare_observation_for_logging_truncates(self, mock_truncate):
        """Test _prepare_observation_for_logging truncates long content."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.content = 'A' * 2000

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 500

        mock_truncate.return_value = 'A' * 500

        result = self.service._prepare_observation_for_logging(mock_observation)

        # Should call truncate_content
        mock_truncate.assert_called_once_with('A' * 2000, 500)
        self.assertEqual(result.content, 'A' * 500)

    async def test_prepare_observation_for_logging_no_truncate(self):
        """Test _prepare_observation_for_logging keeps short content."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.content = 'Short'

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 1000

        result = self.service._prepare_observation_for_logging(mock_observation)

        # Should keep original content
        self.assertEqual(result.content, 'Short')

    async def test_handle_pending_action_observation_no_pending(self):
        """Test _handle_pending_action_observation when no pending action."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        self.mock_pending_service.get.return_value = None

        await self.service._handle_pending_action_observation(mock_observation)

        # Should not proceed with observation handling
        self.mock_context.pop_action_context.assert_not_called()

    async def test_handle_pending_action_observation_cause_mismatch(self):
        """Mismatch clears pending, emits recovery ErrorObservation, and advances step."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-456'
        self.mock_pending_service.peek_for_cause.return_value = None
        self.mock_pending_service.get.return_value = mock_pending_action

        self.mock_context.discard_invocation_context_for_action = MagicMock()
        self.mock_context.emit_event = MagicMock()
        self.mock_context.trigger_step = MagicMock()

        await self.service._handle_pending_action_observation(mock_observation)

        self.mock_context.discard_invocation_context_for_action.assert_called_once_with(
            mock_pending_action
        )
        self.mock_pending_service.set.assert_called_once_with(None)
        emit_args = self.mock_context.emit_event.call_args[0]
        self.assertIsInstance(emit_args[0], ErrorObservation)
        self.assertEqual(emit_args[0].error_id, 'OBSERVATION_PENDING_MISMATCH')
        self.assertIn('Pending action id was', emit_args[0].content)
        self.mock_context.trigger_step.assert_called_once_with()

        self.mock_context.pop_action_context.assert_not_called()
        self.mock_controller.log.assert_called_once()
        log_args = self.mock_controller.log.call_args[0]
        self.assertEqual(log_args[0], 'warning')
        self.assertIn('did not match pending action', log_args[1])

    async def test_late_observation_after_timeout_is_ignored_without_pending(self):
        """A late observation after timeout should not emit a false mismatch warning."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        self.mock_pending_service.get.return_value = None

        await self.service._handle_pending_action_observation(mock_observation)

        self.mock_pending_service.set.assert_not_called()
        self.mock_context.trigger_step.assert_not_called()
        self.mock_controller.log.assert_not_called()

    async def test_stale_numeric_cause_dropped_without_pairing_newer_pending(self):
        """Late obs for a cleared int id must not use get() / primary pending → false mismatch."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 24

        self.mock_pending_service.peek_for_cause.return_value = None
        self.mock_pending_service.has_outstanding_for_cause.return_value = False
        newer = MagicMock()
        newer.id = 25
        self.mock_pending_service.get.return_value = newer

        self.mock_context.emit_event = MagicMock()

        await self.service._handle_pending_action_observation(mock_observation)

        self.mock_pending_service.get.assert_not_called()
        self.mock_context.emit_event.assert_not_called()
        self.mock_pending_service.set.assert_not_called()
        self.mock_context.trigger_step.assert_not_called()
        self.mock_context.pop_action_context.assert_not_called()

    async def test_handle_pending_action_observation_matches_int_like_ids(self):
        """Cause matching should tolerate int/string normalization."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 123

        mock_pending_action = MagicMock()
        mock_pending_action.id = '123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING
        self.mock_context.pop_action_context.return_value = None

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service._handle_pending_action_observation(mock_observation)

        self.mock_pending_service.pop_for_cause.assert_called_with('123')
        self.mock_pending_service.set.assert_not_called()

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_handle_pending_action_observation_plugin_hook(
        self, mock_get_registry
    ):
        """Test _handle_pending_action_observation fires plugin hook."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING

        self.mock_context.pop_action_context.return_value = None

        mock_registry = MagicMock()
        mock_registry.dispatch_action_post = AsyncMock(return_value=mock_observation)
        mock_get_registry.return_value = mock_registry

        await self.service._handle_pending_action_observation(mock_observation)

        # Should dispatch to plugin
        mock_registry.dispatch_action_post.assert_called_once_with(
            mock_pending_action, mock_observation
        )
        self.mock_pending_service.pop_for_cause.assert_called()

    @patch('backend.core.plugin.get_plugin_registry')
    async def test_handle_pending_action_observation_plugin_exception(
        self, mock_get_registry
    ):
        """Test _handle_pending_action_observation handles plugin exceptions."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING

        self.mock_context.pop_action_context.return_value = None

        mock_registry = MagicMock()
        mock_registry.dispatch_action_post = AsyncMock(
            side_effect=RuntimeError('Plugin error')
        )
        mock_get_registry.return_value = mock_registry

        # Should not raise exception
        await self.service._handle_pending_action_observation(mock_observation)

        self.mock_pending_service.pop_for_cause.assert_called()
        self.mock_pending_service.set.assert_not_called()

    async def test_handle_pending_action_observation_awaiting_confirmation(self):
        """Test _handle_pending_action_observation skips processing when awaiting confirmation."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.AWAITING_USER_CONFIRMATION

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service._handle_pending_action_observation(mock_observation)

        # Should not pop context or consume pending when awaiting confirmation
        self.mock_context.pop_action_context.assert_not_called()
        self.mock_pending_service.pop_for_cause.assert_not_called()
        self.mock_pending_service.set.assert_not_called()

    async def test_handle_pending_action_observation_with_confirmation_service(self):
        """Test _handle_pending_action_observation delegates to confirmation service."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING

        mock_ctx = MagicMock()
        self.mock_context.pop_action_context.return_value = mock_ctx

        mock_confirmation = MagicMock()
        mock_confirmation.handle_observation_for_pending_action = AsyncMock()
        self.mock_controller.confirmation_service = mock_confirmation

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service._handle_pending_action_observation(mock_observation)

        # Should delegate to confirmation service
        mock_confirmation.handle_observation_for_pending_action.assert_called_once_with(
            mock_observation, mock_ctx
        )
        self.mock_context.trigger_step.assert_called_once_with()
        self.mock_pending_service.pop_for_cause.assert_called()

    async def test_matching_observation_clears_pending_before_single_step_trigger(self):
        """Resolved observations should clear pending state and advance exactly once."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING
        self.mock_controller.confirmation_service = self.mock_confirmation_service

        mock_ctx = MagicMock()
        self.mock_context.pop_action_context.return_value = mock_ctx

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service._handle_pending_action_observation(mock_observation)

        self.mock_pending_service.pop_for_cause.assert_called()
        self.mock_confirmation_service.handle_observation_for_pending_action.assert_called_once_with(
            mock_observation, mock_ctx
        )
        self.mock_context.trigger_step.assert_called_once_with()

    @patch(
        'backend.orchestration.services.observation_service.transition_agent_state_logic'
    )
    async def test_handle_pending_action_observation_no_confirmation_service(
        self, mock_transition
    ):
        """Test _handle_pending_action_observation uses transition logic when no confirmation service."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = 'action-123'

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.peek_for_cause.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING
        self.mock_controller.confirmation_service = None

        mock_ctx = MagicMock()
        self.mock_context.pop_action_context.return_value = mock_ctx

        mock_transition.return_value = AsyncMock()

        with patch('backend.core.plugin.get_plugin_registry'):
            await self.service._handle_pending_action_observation(mock_observation)

        # Should call transition logic
        mock_transition.assert_called_once_with(
            self.mock_controller, mock_ctx, mock_observation
        )
        self.mock_context.trigger_step.assert_called_once_with()
        self.mock_pending_service.pop_for_cause.assert_called()

    async def test_handle_pending_action_observation_none_cause(self):
        """Test _handle_pending_action_observation handles None cause."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = None

        mock_pending_action = MagicMock()
        mock_pending_action.id = 'action-123'
        self.mock_pending_service.get.return_value = mock_pending_action

        # Should not pop action context for None cause
        self.mock_context.pop_action_context.assert_not_called()


class TestTransitionAgentStateLogic(unittest.IsolatedAsyncioTestCase):
    """Test transition_agent_state_logic helper function."""

    async def test_transition_from_user_confirmed(self):
        """Test transition from USER_CONFIRMED to RUNNING."""
        mock_controller = MagicMock()
        mock_controller.state = MagicMock()
        mock_controller.state.agent_state = AgentState.USER_CONFIRMED
        mock_controller.set_agent_state_to = AsyncMock()

        mock_ctx = None
        mock_observation = MagicMock()

        await transition_agent_state_logic(mock_controller, mock_ctx, mock_observation)

        # Should transition to RUNNING
        mock_controller.set_agent_state_to.assert_called_once_with(AgentState.RUNNING)

    async def test_transition_from_user_rejected(self):
        """Test transition from USER_REJECTED to AWAITING_USER_INPUT."""
        mock_controller = MagicMock()
        mock_controller.state = MagicMock()
        mock_controller.state.agent_state = AgentState.USER_REJECTED
        mock_controller.set_agent_state_to = AsyncMock()

        mock_ctx = None
        mock_observation = MagicMock()

        await transition_agent_state_logic(mock_controller, mock_ctx, mock_observation)

        # Should transition to AWAITING_USER_INPUT
        mock_controller.set_agent_state_to.assert_called_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    async def test_transition_from_running(self):
        """Test no transition from RUNNING state."""
        mock_controller = MagicMock()
        mock_controller.state = MagicMock()
        mock_controller.state.agent_state = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()

        mock_ctx = None
        mock_observation = MagicMock()

        await transition_agent_state_logic(mock_controller, mock_ctx, mock_observation)

        # Should not change state
        mock_controller.set_agent_state_to.assert_not_called()

    async def test_transition_with_pipeline(self):
        """Test transition runs pipeline observe when context provided."""
        mock_controller = MagicMock()
        mock_controller.state = MagicMock()
        mock_controller.state.agent_state = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        mock_controller._cleanup_action_context = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.run_observe = AsyncMock()
        mock_controller.tool_pipeline = mock_pipeline

        mock_ctx = MagicMock()
        mock_observation = MagicMock()

        await transition_agent_state_logic(mock_controller, mock_ctx, mock_observation)

        # Should run observe and cleanup
        mock_pipeline.run_observe.assert_called_once_with(mock_ctx, mock_observation)
        mock_controller._cleanup_action_context.assert_called_once_with(mock_ctx)

    async def test_transition_no_pipeline(self):
        """Test transition handles missing pipeline gracefully."""
        mock_controller = MagicMock()
        mock_controller.state = MagicMock()
        mock_controller.state.agent_state = AgentState.RUNNING
        mock_controller.set_agent_state_to = AsyncMock()
        mock_controller.tool_pipeline = None

        mock_ctx = MagicMock()
        mock_observation = MagicMock()

        # Should not raise exception
        await transition_agent_state_logic(mock_controller, mock_ctx, mock_observation)


if __name__ == '__main__':
    unittest.main()
