"""Tests for ActionService."""

import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from backend.ledger.action import Action, NullAction
from backend.orchestration.services.action_service import ActionService


class TestActionService(unittest.IsolatedAsyncioTestCase):
    """Test ActionService action processing and lifecycle."""

    def setUp(self):
        """Create mock dependencies for testing."""
        self.mock_context = MagicMock()
        self.mock_controller = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller

        # Setup metrics mocks needed for _prepare_metrics_for_action
        self.mock_controller.conversation_stats = MagicMock()
        self.mock_controller.conversation_stats.get_combined_metrics.return_value = (
            MagicMock(
                accumulated_cost=0.0,
                accumulated_token_usage=MagicMock(),
                max_budget_per_task=None,
            )
        )
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.budget_flag = None
        self.mock_controller.state.metrics = MagicMock()
        self.mock_controller.state.metrics.token_usages = []
        self.mock_controller.state.metrics.accumulated_token_usage = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.handle_blocked_invocation = MagicMock()

        self.mock_pending_service = MagicMock()
        self.mock_confirmation_service = MagicMock()
        self.mock_confirmation_service.evaluate_action = AsyncMock()
        self.mock_confirmation_service.handle_pending_confirmation = AsyncMock()

        self.service = ActionService(
            self.mock_context, self.mock_pending_service, self.mock_confirmation_service
        )

    async def test_run_non_action_type(self):
        """Test run raises TypeError for non-Action input."""
        with self.assertRaises(TypeError):
            await self.service.run(cast(Any, 'not an action'), None)

    async def test_run_non_runnable_action(self):
        """Test run skips runnable handling for non-runnable actions."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = False

        await self.service.run(mock_action, None)

        # Should not call evaluate_action for non-runnable
        self.mock_confirmation_service.evaluate_action.assert_not_called()

    async def test_run_runnable_action_not_blocked(self):
        """Test run processes runnable action through full pipeline."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True
        mock_action.id = 'action-123'
        mock_action.source = None

        mock_ctx = MagicMock()
        mock_ctx.blocked = False
        mock_ctx.action_id = None

        mock_pipeline = MagicMock()
        mock_pipeline.run_execute = AsyncMock()
        self.mock_controller.operation_pipeline = mock_pipeline
        # Override default cost for this specific test
        self.mock_controller.conversation_stats.get_combined_metrics.return_value.accumulated_cost = 10.5

        await self.service.run(mock_action, mock_ctx)

        # Should evaluate action
        self.mock_confirmation_service.evaluate_action.assert_called_once_with(
            mock_action
        )

        # Should set pending (action is runnable)
        self.mock_pending_service.set.assert_called()

        # Should handle confirmation
        self.mock_confirmation_service.handle_pending_confirmation.assert_called_once()

        # Should run execute
        mock_pipeline.run_execute.assert_called_once_with(mock_ctx)

    async def test_run_blocked_during_execute(self):
        """Test run stops when action is blocked during execute."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True

        mock_ctx = MagicMock()
        mock_ctx.blocked = False

        async def set_blocked(*args):
            mock_ctx.blocked = True

        mock_pipeline = MagicMock()
        mock_pipeline.run_execute = AsyncMock(side_effect=set_blocked)
        self.mock_controller.operation_pipeline = mock_pipeline

        await self.service.run(mock_action, mock_ctx)

        # Should stop after execute blocks
        self.mock_controller.handle_blocked_invocation.assert_called_once_with(
            mock_action, mock_ctx
        )

    async def test_run_blocked_after_runnable(self):
        """Test run handles blocked action after runnable processing."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True
        mock_action.source = None

        mock_ctx = MagicMock()
        mock_ctx.blocked = False
        mock_ctx.action_id = None

        mock_pipeline = MagicMock()
        mock_pipeline.run_execute = AsyncMock()
        self.mock_controller.operation_pipeline = mock_pipeline

        await self.service.run(mock_action, mock_ctx)

        # evaluate_action is still called (blocking happens in execute, not before)
        self.mock_confirmation_service.evaluate_action.assert_called_once()

    async def test_run_null_action_skips_finalize(self):
        """Test run handles missing tool_pipeline gracefully."""
        mock_action = MagicMock(spec=Action)
        mock_action.runnable = True
        mock_action.source = None

        self.mock_controller.operation_pipeline = None
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.conversation_stats = MagicMock()
        self.mock_controller.conversation_stats.get_combined_metrics.return_value = (
            MagicMock(accumulated_cost=0, accumulated_token_usage=MagicMock())
        )
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.budget_flag = None
        self.mock_controller.state.metrics = MagicMock()
        self.mock_controller.state.metrics.token_usages = []
        self.mock_controller.state.metrics.accumulated_token_usage = MagicMock()
        self.mock_controller.log = MagicMock()

        await self.service.run(mock_action, None)

        # Should still process action
        self.mock_confirmation_service.evaluate_action.assert_called_once()

    def test_prepare_metrics_for_action(self):
        """Test _prepare_metrics_for_action attaches metrics to action."""
        mock_action = MagicMock()

        mock_metrics = MagicMock()
        mock_metrics.accumulated_cost = 15.75
        mock_metrics.accumulated_token_usage = MagicMock()
        mock_metrics.max_budget_per_task = None

        self.mock_controller.conversation_stats = MagicMock()
        self.mock_controller.conversation_stats.get_combined_metrics.return_value = (
            mock_metrics
        )

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.budget_flag = MagicMock()
        self.mock_controller.state.budget_flag.max_value = 50.0
        self.mock_controller.state.metrics = MagicMock()
        self.mock_controller.state.metrics.token_usages = []
        self.mock_controller.state.metrics.accumulated_token_usage = MagicMock(
            prompt_tokens=100, completion_tokens=50
        )
        self.mock_controller.log = MagicMock()

        self.service._prepare_metrics_for_action(mock_action)

        # Should attach metrics to action
        self.assertIsNotNone(mock_action.llm_metrics)
        self.assertEqual(mock_action.llm_metrics.accumulated_cost, 15.75)
        self.assertEqual(mock_action.llm_metrics.max_budget_per_task, 50.0)

    def test_prepare_metrics_for_action_no_budget_flag(self):
        """Test _prepare_metrics_for_action without budget flag."""
        mock_action = MagicMock()

        mock_metrics = MagicMock()
        mock_metrics.accumulated_cost = 10.0
        mock_metrics.accumulated_token_usage = MagicMock()

        self.mock_controller.conversation_stats = MagicMock()
        self.mock_controller.conversation_stats.get_combined_metrics.return_value = (
            mock_metrics
        )

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.budget_flag = None
        self.mock_controller.state.metrics = MagicMock()
        self.mock_controller.state.metrics.token_usages = []
        self.mock_controller.state.metrics.accumulated_token_usage = MagicMock()
        self.mock_controller.log = MagicMock()

        self.service._prepare_metrics_for_action(mock_action)

        # Should still attach metrics
        self.assertIsNotNone(mock_action.llm_metrics)

    def test_prepare_metrics_for_action_with_latest_usage(self):
        """Test _prepare_metrics_for_action logs latest token usage."""
        mock_action = MagicMock()

        mock_metrics = MagicMock()
        mock_metrics.accumulated_cost = 5.0
        mock_metrics.accumulated_token_usage = MagicMock()
        mock_metrics.max_budget_per_task = None

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 200
        mock_usage.completion_tokens = 150
        mock_usage.cache_read_tokens = 50
        mock_usage.cache_write_tokens = 25

        self.mock_controller.conversation_stats = MagicMock()
        self.mock_controller.conversation_stats.get_combined_metrics.return_value = (
            mock_metrics
        )

        self.mock_controller.state = MagicMock()
        self.mock_controller.state.budget_flag = None
        self.mock_controller.state.metrics = MagicMock()
        self.mock_controller.state.metrics.token_usages = [mock_usage]
        self.mock_controller.state.metrics.accumulated_token_usage = MagicMock(
            prompt_tokens=500, completion_tokens=300
        )
        self.mock_controller.log = MagicMock()

        self.service._prepare_metrics_for_action(mock_action)

        # Should log detailed metrics
        self.mock_controller.log.assert_called()
        call_args = self.mock_controller.log.call_args[0]
        self.assertIn('200', call_args[1])  # prompt tokens
        self.assertIn('150', call_args[1])  # completion tokens

    def test_set_pending_action(self):
        """Test set_pending_action delegates to pending service."""
        mock_action = MagicMock()

        self.service.set_pending_action(mock_action)

        self.mock_pending_service.set.assert_called_once_with(mock_action)

    def test_set_pending_action_none(self):
        """Test set_pending_action can clear pending action."""
        self.service.set_pending_action(None)

        self.mock_pending_service.set.assert_called_once_with(None)

    def test_get_pending_action(self):
        """Test get_pending_action delegates to pending service."""
        mock_action = MagicMock()
        self.mock_pending_service.get.return_value = mock_action

        result = self.service.get_pending_action()

        self.assertEqual(result, mock_action)
        self.mock_pending_service.get.assert_called_once()

    def test_get_pending_action_info(self):
        """Test get_pending_action_info returns action and timestamp."""
        mock_action = MagicMock()
        mock_info = (mock_action, 123.456)
        self.mock_pending_service.info.return_value = mock_info

        result = self.service.get_pending_action_info()

        self.assertEqual(result, mock_info)
        self.mock_pending_service.info.assert_called_once()

    def test_get_pending_action_info_none(self):
        """Test get_pending_action_info returns None when no pending action."""
        self.mock_pending_service.info.return_value = None

        result = self.service.get_pending_action_info()

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
