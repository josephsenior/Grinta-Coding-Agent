"""Tests for ActionExecutionService."""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.orchestration.services.action_execution_service import ActionExecutionService
from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoActionError,
    LLMResponseError,
)
from backend.ledger import EventSource
from backend.ledger.action import Action
from backend.ledger.action.agent import CondensationRequestAction
from backend.inference.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    RateLimitError,
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
        self.mock_context.agent.step.side_effect = LLMMalformedActionError("Bad action")

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)
        self.mock_context.event_stream.add_event.assert_called_once()

    async def test_get_next_action_no_action_error(self):
        """Test get_next_action handles LLMNoActionError."""
        self.mock_context.agent.step.side_effect = LLMNoActionError("No action")

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)
        self.mock_context.event_stream.add_event.assert_called_once()

    async def test_get_next_action_response_error(self):
        """Test get_next_action handles LLMResponseError."""
        self.mock_context.agent.step.side_effect = LLMResponseError("Response error")

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)

    async def test_get_next_action_function_validation_error(self):
        """Test get_next_action handles FunctionCallValidationError."""
        self.mock_context.agent.step.side_effect = FunctionCallValidationError(
            "Invalid"
        )

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)

    async def test_get_next_action_function_not_exists_error(self):
        """Test get_next_action handles FunctionCallNotExistsError."""
        self.mock_context.agent.step.side_effect = FunctionCallNotExistsError(
            "Not found"
        )

        result = await self.service.get_next_action()

        # Should return None and emit error
        self.assertIsNone(result)

    async def test_get_next_action_context_window_exceeded(self):
        """Test get_next_action handles context window exceeded."""
        self.mock_context.agent.step.side_effect = ContextWindowExceededError(
            "Too large"
        )
        self.mock_context.agent.config.enable_history_truncation = True

        with patch.object(
            self.service, "_handle_context_window_error", new_callable=AsyncMock
        ) as mock_handle:
            mock_handle.return_value = None
            await self.service.get_next_action()

        # Should delegate to context window handler
        mock_handle.assert_called_once()

    async def test_get_next_action_api_connection_error_raises(self):
        """Test get_next_action raises APIConnectionError."""
        self.mock_context.agent.step.side_effect = APIConnectionError(
            "Connection failed"
        )

        with self.assertRaises(APIConnectionError):
            await self.service.get_next_action()

    async def test_get_next_action_authentication_error_raises(self):
        """Test get_next_action raises AuthenticationError."""
        self.mock_context.agent.step.side_effect = AuthenticationError("Auth failed")

        with self.assertRaises(AuthenticationError):
            await self.service.get_next_action()

    async def test_get_next_action_rate_limit_error_raises(self):
        """Test get_next_action raises RateLimitError."""
        self.mock_context.agent.step.side_effect = RateLimitError("Rate limited")

        with self.assertRaises(RateLimitError):
            await self.service.get_next_action()

    async def test_execute_action_runnable_with_pipeline(self):
        """Test execute_action processes runnable action through pipeline."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True

        mock_ctx = MagicMock()
        mock_ctx.blocked = False

        mock_pipeline = MagicMock()
        mock_pipeline.create_context = MagicMock(return_value=mock_ctx)
        mock_pipeline.run_plan = AsyncMock()
        self.mock_context.operation_pipeline = mock_pipeline

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service.execute_action(mock_action)

        # Should create context and run plan
        mock_pipeline.create_context.assert_called_once_with(
            mock_action, self.mock_context.state
        )
        self.mock_context.register_action_context.assert_called_once_with(
            mock_action, mock_ctx
        )
        mock_pipeline.run_plan.assert_called_once_with(mock_ctx)

        # Should apply dynamic iterations
        self.mock_context.iteration_service.apply_dynamic_iterations.assert_called_once_with(
            mock_ctx
        )

        # Should run action
        self.mock_context.run_action.assert_called_once_with(mock_action, mock_ctx)

    async def test_execute_action_blocked_during_plan(self):
        """Test execute_action handles blocked action during plan."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True

        mock_ctx = MagicMock()
        mock_ctx.blocked = True

        mock_pipeline = MagicMock()
        mock_pipeline.create_context = MagicMock(return_value=mock_ctx)
        mock_pipeline.run_plan = AsyncMock()
        self.mock_context.operation_pipeline = mock_pipeline

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service.execute_action(mock_action)

        # Should handle blocked invocation
        self.mock_context.telemetry_service.handle_blocked_invocation.assert_called_once_with(
            mock_action, mock_ctx
        )

        # Should not run action
        self.mock_context.run_action.assert_not_called()

    async def test_execute_action_non_runnable(self):
        """Test execute_action processes non-runnable action."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service.execute_action(mock_action)

        # Should run action without pipeline
        self.mock_context.run_action.assert_called_once_with(mock_action, None)

    async def test_execute_action_no_pipeline(self):
        """Test execute_action handles missing pipeline."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True

        self.mock_context.operation_pipeline = None

        with patch("backend.core.plugin.get_plugin_registry"):
            await self.service.execute_action(mock_action)

        # Should run action without pipeline processing
        self.mock_context.run_action.assert_called_once()

    @patch("backend.core.plugin.get_plugin_registry")
    async def test_execute_action_plugin_hook(self, mock_get_registry):
        """Test execute_action fires plugin pre-action hook."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(return_value=mock_action)
        mock_get_registry.return_value = mock_registry

        await self.service.execute_action(mock_action)

        # Should dispatch to plugin
        mock_registry.dispatch_action_pre.assert_called_once_with(mock_action)

    @patch("backend.core.plugin.get_plugin_registry")
    async def test_execute_action_plugin_exception(self, mock_get_registry):
        """Test execute_action handles plugin exceptions gracefully."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        mock_registry = MagicMock()
        mock_registry.dispatch_action_pre = AsyncMock(
            side_effect=RuntimeError("Plugin error")
        )
        mock_get_registry.return_value = mock_registry

        # Should not raise exception
        await self.service.execute_action(mock_action)

        # Should still run action
        self.mock_context.run_action.assert_called_once()

    @patch(
        "backend.orchestration.services.action_execution_service.is_context_window_error"
    )
    async def test_handle_context_window_error_with_truncation(self, mock_is_ctx_error):
        """Test _handle_context_window_error emits condensation request."""
        exc = ContextWindowExceededError("Context too large")
        mock_is_ctx_error.return_value = True
        self.mock_context.agent.config.enable_history_truncation = True

        result = await self.service._handle_context_window_error(exc)

        # Should emit condensation request
        self.assertIsNone(result)
        self.mock_context.event_stream.add_event.assert_called_once()

        # Check for CondensationRequestAction
        call_args = self.mock_context.event_stream.add_event.call_args[0]
        self.assertIsInstance(call_args[0], CondensationRequestAction)

    @patch(
        "backend.orchestration.services.action_execution_service.is_context_window_error"
    )
    async def test_handle_context_window_error_without_truncation(
        self, mock_is_ctx_error
    ):
        """Test _handle_context_window_error raises when truncation disabled."""
        exc = ContextWindowExceededError("Context too large")
        mock_is_ctx_error.return_value = True
        self.mock_context.agent.config.enable_history_truncation = False

        with self.assertRaises(LLMContextWindowExceedError):
            await self.service._handle_context_window_error(exc)

    @patch(
        "backend.orchestration.services.action_execution_service.is_context_window_error"
    )
    async def test_handle_context_window_error_not_context_window(
        self, mock_is_ctx_error
    ):
        """Test _handle_context_window_error re-raises non-context-window errors."""
        exc = BadRequestError("Bad request")
        mock_is_ctx_error.return_value = False

        with self.assertRaises(BadRequestError):
            await self.service._handle_context_window_error(exc)


if __name__ == "__main__":
    unittest.main()
