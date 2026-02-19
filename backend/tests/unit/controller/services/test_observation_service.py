"""Tests for ObservationService."""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.controller.services.observation_service import (
    ObservationService,
    transition_agent_state_logic,
)
from backend.controller.state.state import AgentState
from backend.events.observation import Observation


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

        self.service = ObservationService(self.mock_context, self.mock_pending_service)

    @patch.dict("os.environ", {"LOG_ALL_EVENTS": "1"})
    async def test_handle_observation_log_all_events(self):
        """Test handle_observation logs at info level when LOG_ALL_EVENTS=1."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = None
        mock_observation.content = "Test observation"

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 1000
        self.mock_controller.log = MagicMock()

        self.mock_pending_service.get.return_value = None

        await self.service.handle_observation(mock_observation)

        # Should log at info level
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], "info")

    @patch.dict("os.environ", {}, clear=True)
    async def test_handle_observation_default_log_level(self):
        """Test handle_observation logs at debug level by default."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = None
        mock_observation.content = "Test"

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 500
        self.mock_controller.log = MagicMock()

        self.mock_pending_service.get.return_value = None

        await self.service.handle_observation(mock_observation)

        # Should log at debug level
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], "debug")

    @patch("backend.controller.services.observation_service.truncate_content")
    async def test_prepare_observation_for_logging_truncates(self, mock_truncate):
        """Test _prepare_observation_for_logging truncates long content."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.content = "A" * 2000

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 500

        mock_truncate.return_value = "A" * 500

        result = self.service._prepare_observation_for_logging(mock_observation)

        # Should call truncate_content
        mock_truncate.assert_called_once_with("A" * 2000, 500)
        self.assertEqual(result.content, "A" * 500)

    async def test_prepare_observation_for_logging_no_truncate(self):
        """Test _prepare_observation_for_logging keeps short content."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.content = "Short"

        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.llm = MagicMock()
        self.mock_controller.agent.llm.config = MagicMock()
        self.mock_controller.agent.llm.config.max_message_chars = 1000

        result = self.service._prepare_observation_for_logging(mock_observation)

        # Should keep original content
        self.assertEqual(result.content, "Short")

    async def test_handle_pending_action_observation_no_pending(self):
        """Test _handle_pending_action_observation when no pending action."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        self.mock_pending_service.get.return_value = None

        await self.service._handle_pending_action_observation(mock_observation)

        # Should not proceed with observation handling
        self.mock_context.pop_action_context.assert_not_called()

    async def test_handle_pending_action_observation_cause_mismatch(self):
        """Test _handle_pending_action_observation when cause doesn't match."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-456"
        self.mock_pending_service.get.return_value = mock_pending_action

        await self.service._handle_pending_action_observation(mock_observation)

        # Should not proceed
        self.mock_context.pop_action_context.assert_not_called()

    @patch("backend.core.plugin.get_plugin_registry")
    async def test_handle_pending_action_observation_plugin_hook(
        self, mock_get_registry
    ):
        """Test _handle_pending_action_observation fires plugin hook."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-123"
        self.mock_pending_service.get.return_value = mock_pending_action

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

    @patch("backend.core.plugin.get_plugin_registry")
    async def test_handle_pending_action_observation_plugin_exception(
        self, mock_get_registry
    ):
        """Test _handle_pending_action_observation handles plugin exceptions."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-123"
        self.mock_pending_service.get.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING

        self.mock_context.pop_action_context.return_value = None

        mock_registry = MagicMock()
        mock_registry.dispatch_action_post = AsyncMock(
            side_effect=RuntimeError("Plugin error")
        )
        mock_get_registry.return_value = mock_registry

        # Should not raise exception
        await self.service._handle_pending_action_observation(mock_observation)

        # Should still clear pending action
        self.mock_pending_service.set.assert_called_once_with(None)

    async def test_handle_pending_action_observation_awaiting_confirmation(self):
        """Test _handle_pending_action_observation skips processing when awaiting confirmation."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-123"
        self.mock_pending_service.get.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.AWAITING_USER_CONFIRMATION

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service._handle_pending_action_observation(mock_observation)

        # Should not pop context or clear pending when awaiting confirmation
        self.mock_context.pop_action_context.assert_not_called()
        self.mock_pending_service.set.assert_not_called()

    async def test_handle_pending_action_observation_with_confirmation_service(self):
        """Test _handle_pending_action_observation delegates to confirmation service."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-123"
        self.mock_pending_service.get.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING

        mock_ctx = MagicMock()
        self.mock_context.pop_action_context.return_value = mock_ctx

        mock_confirmation = MagicMock()
        mock_confirmation.handle_observation_for_pending_action = AsyncMock()
        self.mock_controller.confirmation_service = mock_confirmation

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service._handle_pending_action_observation(mock_observation)

        # Should delegate to confirmation service
        mock_confirmation.handle_observation_for_pending_action.assert_called_once_with(
            mock_observation, mock_ctx
        )

    @patch(
        "backend.controller.services.observation_service.transition_agent_state_logic"
    )
    async def test_handle_pending_action_observation_no_confirmation_service(
        self, mock_transition
    ):
        """Test _handle_pending_action_observation uses transition logic when no confirmation service."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = "action-123"

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-123"
        self.mock_pending_service.get.return_value = mock_pending_action

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.agent_state = AgentState.RUNNING
        self.mock_controller.confirmation_service = None

        mock_ctx = MagicMock()
        self.mock_context.pop_action_context.return_value = mock_ctx

        mock_transition.return_value = AsyncMock()

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service._handle_pending_action_observation(mock_observation)

        # Should call transition logic
        mock_transition.assert_called_once_with(
            self.mock_controller, mock_ctx, mock_observation
        )

    async def test_handle_pending_action_observation_none_cause(self):
        """Test _handle_pending_action_observation handles None cause."""
        mock_observation = MagicMock(spec=Observation)
        mock_observation.cause = None

        mock_pending_action = MagicMock()
        mock_pending_action.id = "action-123"
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


if __name__ == "__main__":
    unittest.main()
