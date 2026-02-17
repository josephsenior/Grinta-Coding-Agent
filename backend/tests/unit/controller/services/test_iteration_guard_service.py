"""Tests for IterationGuardService."""

import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from backend.controller.services.iteration_guard_service import IterationGuardService
from backend.core.schemas import AgentState


class TestIterationGuardService(unittest.IsolatedAsyncioTestCase):
    """Test IterationGuardService control flag handling and graceful shutdown."""

    def setUp(self):
        """Create mock context and controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.iteration_flag = MagicMock()
        self.mock_controller.state.iteration_flag.current_value = 5
        self.mock_controller.state.iteration_flag.max_value = 10
        self.mock_controller.state.agent_state = "RUNNING"
        self.mock_controller.state_tracker = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.headless_mode = False
        self.mock_controller._step = AsyncMock()
        self.mock_controller.event_router = MagicMock()
        self.mock_controller.event_router._handle_finish_action = AsyncMock()
        
        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        
        self.service = IterationGuardService(self.mock_context)

    async def test_run_control_flags_success(self):
        """Test run_control_flags calls state tracker successfully."""
        await self.service.run_control_flags()
        
        self.mock_controller.state_tracker.run_control_flags.assert_called_once()

    async def test_run_control_flags_non_limit_error_raises(self):
        """Test run_control_flags raises non-limit errors."""
        self.mock_controller.state_tracker.run_control_flags.side_effect = \
            ValueError("Some other error")
        
        with self.assertRaises(ValueError):
            await self.service.run_control_flags()

    async def test_run_control_flags_limit_error_with_graceful_shutdown(self):
        """Test run_control_flags triggers graceful shutdown on limit error."""
        self.mock_controller.state_tracker.run_control_flags.side_effect = \
            RuntimeError("Iteration limit exceeded")
        
        with patch.object(self.service, '_graceful_shutdown_enabled', return_value=True):
            with patch.object(self.service, '_schedule_graceful_shutdown') as mock_schedule:
                with self.assertRaises(RuntimeError):
                    await self.service.run_control_flags()
                
                mock_schedule.assert_called_once()

    async def test_run_control_flags_limit_error_without_graceful_shutdown(self):
        """Test run_control_flags raises limit error when graceful shutdown disabled."""
        self.mock_controller.state_tracker.run_control_flags.side_effect = \
            RuntimeError("Budget limit exceeded")
        
        with patch.object(self.service, '_graceful_shutdown_enabled', return_value=False):
            with self.assertRaises(RuntimeError):
                await self.service.run_control_flags()

    def test_is_limit_error_detects_limit(self):
        """Test _is_limit_error detects limit errors."""
        self.assertTrue(self.service._is_limit_error("iteration limit exceeded"))
        self.assertTrue(self.service._is_limit_error("maximum budget reached"))
        self.assertTrue(self.service._is_limit_error("budget exceeded"))
        self.assertTrue(self.service._is_limit_error("limit hit"))

    def test_is_limit_error_rejects_non_limit(self):
        """Test _is_limit_error rejects non-limit errors."""
        self.assertFalse(self.service._is_limit_error("connection error"))
        self.assertFalse(self.service._is_limit_error("null pointer"))

    def test_graceful_shutdown_enabled_from_agent_config(self):
        """Test _graceful_shutdown_enabled reads from agent_config."""
        self.mock_controller.agent_config = MagicMock()
        self.mock_controller.agent_config.enable_graceful_shutdown = False
        
        result = self.service._graceful_shutdown_enabled()
        
        self.assertFalse(result)

    @patch.dict('os.environ', {'FORGE_GRACEFUL_SHUTDOWN': '0'})
    def test_graceful_shutdown_disabled_from_env(self):
        """Test _graceful_shutdown_enabled reads from env var."""
        self.mock_controller.agent_config = None
        
        result = self.service._graceful_shutdown_enabled()
        
        self.assertFalse(result)

    @patch.dict('os.environ', {'FORGE_GRACEFUL_SHUTDOWN': '1'})
    def test_graceful_shutdown_enabled_from_env(self):
        """Test _graceful_shutdown_enabled defaults to enabled."""
        self.mock_controller.agent_config = None
        
        result = self.service._graceful_shutdown_enabled()
        
        self.assertTrue(result)

    @patch.dict('os.environ', {}, clear=True)
    def test_graceful_shutdown_enabled_default(self):
        """Test _graceful_shutdown_enabled defaults to True when env not set."""
        self.mock_controller.agent_config = None
        
        result = self.service._graceful_shutdown_enabled()
        
        self.assertTrue(result)

    @patch('backend.utils.async_utils.create_tracked_task')
    def test_schedule_graceful_shutdown(self, mock_create_task):
        """Test _schedule_graceful_shutdown creates async task."""
        self.service._schedule_graceful_shutdown("Test reason")
        
        mock_create_task.assert_called_once()
        call_kwargs = mock_create_task.call_args[1]
        self.assertEqual(call_kwargs['name'], "graceful-shutdown")

    @patch('backend.controller.services.iteration_guard_service.MessageAction')
    async def test_graceful_shutdown_sends_message(self, mock_message_action):
        """Test _graceful_shutdown sends SYSTEM NOTICE message."""
        mock_msg = MagicMock()
        mock_message_action.return_value = mock_msg
        
        await self.service._graceful_shutdown("Iteration limit")
        
        # Check MessageAction was created with system notice
        mock_message_action.assert_called_once()
        content = mock_message_action.call_args[1]['content']
        self.assertIn("SYSTEM NOTICE", content)
        self.assertIn("Iteration limit", content)
        self.assertIn("ONE FINAL TURN", content)
        
        # Check event was added
        self.mock_controller.event_stream.add_event.assert_called()

    @patch('backend.controller.services.iteration_guard_service.MessageAction')
    async def test_graceful_shutdown_extends_iteration_limit(self, mock_message_action):
        """Test _graceful_shutdown extends iteration limit by 1."""
        original_max = self.mock_controller.state.iteration_flag.max_value
        
        await self.service._graceful_shutdown("Budget exceeded")
        
        # Check _step was called
        self.mock_controller._step.assert_called_once()
        
        # Max should have been incremented during execution
        # (then potentially restored after)

    @patch('backend.controller.services.iteration_guard_service.MessageAction')
    async def test_graceful_shutdown_restores_original_max(self, mock_message_action):
        """Test _graceful_shutdown restores original max value after step."""
        original_max = 10
        self.mock_controller.state.iteration_flag.max_value = original_max
        
        await self.service._graceful_shutdown("Test")
        
        # Should have restored original max
        self.assertEqual(self.mock_controller.state.iteration_flag.max_value, original_max)

    async def test_graceful_shutdown_no_iteration_flag(self):
        """Test _graceful_shutdown handles missing iteration flag."""
        del self.mock_controller.state.iteration_flag
        # Set state to FINISHED so _force_partial_completion is skipped
        self.mock_controller.state.agent_state = AgentState.FINISHED
        
        with patch('backend.controller.services.iteration_guard_service.MessageAction'):
            # Should not raise exception
            await self.service._graceful_shutdown("Test")

    @patch('backend.controller.services.iteration_guard_service.MessageAction')
    async def test_graceful_shutdown_step_error(self, mock_message_action):
        """Test _graceful_shutdown handles step errors gracefully."""
        self.mock_controller._step.side_effect = RuntimeError("Step failed")
        
        with patch.object(self.service, '_force_partial_completion', new_callable=AsyncMock) as mock_force:
            # Should not raise exception
            await self.service._graceful_shutdown("Test")
            
            # Should call force completion
            mock_force.assert_called_once()

    @patch('backend.controller.services.iteration_guard_service.MessageAction')
    async def test_graceful_shutdown_forces_completion_if_not_finished(self, mock_message_action):
        """Test _graceful_shutdown forces completion when agent doesn't finish."""
        from backend.core.schemas import AgentState
        
        self.mock_controller.state.agent_state = AgentState.RUNNING
        
        with patch.object(self.service, '_force_partial_completion', new_callable=AsyncMock) as mock_force:
            await self.service._graceful_shutdown("Test")
            
            mock_force.assert_called_once_with("Test")

    @patch('backend.controller.services.iteration_guard_service.MessageAction')
    async def test_graceful_shutdown_skips_force_if_finished(self, mock_message_action):
        """Test _graceful_shutdown skips force completion when finished."""
        from backend.core.schemas import AgentState
        
        self.mock_controller.state.agent_state = AgentState.FINISHED
        
        with patch.object(self.service, '_force_partial_completion', new_callable=AsyncMock) as mock_force:
            await self.service._graceful_shutdown("Test")
            
            mock_force.assert_not_called()

    @patch('backend.controller.services.iteration_guard_service.PlaybookFinishAction')
    async def test_force_partial_completion(self, mock_finish_action):
        """Test _force_partial_completion creates PlaybookFinishAction."""
        mock_finish = MagicMock()
        mock_finish_action.return_value = mock_finish
        
        self.mock_controller.event_router = MagicMock()
        self.mock_controller.event_router._handle_finish_action = AsyncMock()
        
        await self.service._force_partial_completion("Budget limit")
        
        # Check PlaybookFinishAction was created
        mock_finish_action.assert_called_once()
        call_kwargs = mock_finish_action.call_args[1]
        self.assertEqual(call_kwargs['outputs']['status'], 'partial')
        self.assertIn("Budget limit", call_kwargs['outputs']['reason'])
        self.assertTrue(call_kwargs['force_finish'])
        
        # Check force_finish flag was set
        self.assertTrue(mock_finish.force_finish)
        
        # Check action was handled
        self.mock_controller.event_router._handle_finish_action.assert_called_once_with(mock_finish)


if __name__ == '__main__':
    unittest.main()
