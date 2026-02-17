"""Tests for StepGuardService."""

import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from backend.controller.services.step_guard_service import StepGuardService


class TestStepGuardService(unittest.IsolatedAsyncioTestCase):
    """Test StepGuardService circuit breaker and stuck detection guards."""

    def setUp(self):
        """Create mock context and controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller._react_to_exception = AsyncMock()
        
        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        
        self.service = StepGuardService(self.mock_context)

    async def test_ensure_can_step_all_checks_pass(self):
        """Test ensure_can_step returns True when all checks pass."""
        self.mock_controller.circuit_breaker_service = None
        self.mock_controller.stuck_service = None
        
        result = await self.service.ensure_can_step()
        
        self.assertTrue(result)

    async def test_ensure_can_step_circuit_breaker_blocks(self):
        """Test ensure_can_step returns False when circuit breaker trips."""
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "Too many errors"
        mock_result.action = "stop"
        mock_result.recommendation = "Fix the errors"
        mock_cb_service.check.return_value = mock_result
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        self.mock_controller.stuck_service = None
        
        result = await self.service.ensure_can_step()
        
        self.assertFalse(result)
        self.mock_controller.event_stream.add_event.assert_called_once()
        self.mock_controller.set_agent_state_to.assert_called_once()

    async def test_ensure_can_step_stuck_detection_blocks(self):
        """Test ensure_can_step returns False when stuck detection triggers."""
        from backend.core.exceptions import AgentStuckInLoopError
        
        self.mock_controller.circuit_breaker_service = None
        
        mock_stuck_service = MagicMock()
        mock_stuck_service.is_stuck.return_value = True
        self.mock_controller.stuck_service = mock_stuck_service
        
        result = await self.service.ensure_can_step()
        
        self.assertFalse(result)
        self.mock_controller._react_to_exception.assert_called_once()
        # Check exception type
        call_args = self.mock_controller._react_to_exception.call_args[0]
        self.assertIsInstance(call_args[0], AgentStuckInLoopError)

    async def test_check_circuit_breaker_no_service(self):
        """Test _check_circuit_breaker returns True when no service."""
        self.mock_controller.circuit_breaker_service = None
        result = await self.service._check_circuit_breaker(self.mock_controller)
        
        self.assertTrue(result)

    async def test_check_circuit_breaker_not_tripped(self):
        """Test _check_circuit_breaker returns True when not tripped."""
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = False
        mock_cb_service.check.return_value = mock_result
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        
        result = await self.service._check_circuit_breaker(self.mock_controller)
        
        self.assertTrue(result)

    async def test_check_circuit_breaker_tripped_stop_action(self):
        """Test _check_circuit_breaker sets STOPPED state for stop action."""
        from backend.core.schemas import AgentState
        
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "Too many errors"
        mock_result.action = "stop"
        mock_result.recommendation = "Fix errors"
        mock_cb_service.check.return_value = mock_result
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        
        result = await self.service._check_circuit_breaker(self.mock_controller)
        
        self.assertFalse(result)
        self.mock_controller.set_agent_state_to.assert_called_once_with(AgentState.STOPPED)

    async def test_check_circuit_breaker_tripped_pause_action(self):
        """Test _check_circuit_breaker sets PAUSED state for non-stop action."""
        from backend.core.schemas import AgentState
        
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "High risk actions"
        mock_result.action = "pause"
        mock_result.recommendation = "Review actions"
        mock_cb_service.check.return_value = mock_result
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        
        result = await self.service._check_circuit_breaker(self.mock_controller)
        
        self.assertFalse(result)
        self.mock_controller.set_agent_state_to.assert_called_once_with(AgentState.PAUSED)

    @patch('backend.controller.services.step_guard_service.ErrorObservation')
    @patch('backend.controller.services.step_guard_service.logger')
    async def test_check_circuit_breaker_logs_and_emits_error(self, mock_logger, mock_error_obs):
        """Test _check_circuit_breaker logs error and emits observation."""
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "Test reason"
        mock_result.action = "stop"
        mock_result.recommendation = "Test recommendation"
        mock_cb_service.check.return_value = mock_result
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        
        mock_obs = MagicMock()
        mock_error_obs.return_value = mock_obs
        
        await self.service._check_circuit_breaker(self.mock_controller)
        
        # Check logger.error was called
        mock_logger.error.assert_called_once()
        
        # Check ErrorObservation was created
        mock_error_obs.assert_called_once()
        call_kwargs = mock_error_obs.call_args[1]
        self.assertIn("CIRCUIT BREAKER TRIPPED", call_kwargs['content'])
        self.assertIn("Test reason", call_kwargs['content'])
        self.assertEqual(call_kwargs['error_id'], "CIRCUIT_BREAKER_TRIPPED")

    async def test_handle_stuck_detection_no_service(self):
        """Test _handle_stuck_detection returns True when no service."""
        self.mock_controller.stuck_service = None
        result = await self.service._handle_stuck_detection(self.mock_controller)
        
        self.assertTrue(result)

    async def test_handle_stuck_detection_not_stuck(self):
        """Test _handle_stuck_detection returns True when not stuck."""
        mock_stuck_service = MagicMock()
        mock_stuck_service.is_stuck.return_value = False
        
        self.mock_controller.stuck_service = mock_stuck_service
        
        result = await self.service._handle_stuck_detection(self.mock_controller)
        
        self.assertTrue(result)

    async def test_handle_stuck_detection_stuck_records_to_circuit_breaker(self):
        """Test _handle_stuck_detection records stuck detection to circuit breaker."""
        from backend.core.exceptions import AgentStuckInLoopError
        
        mock_stuck_service = MagicMock()
        mock_stuck_service.is_stuck.return_value = True
        
        mock_cb_service = MagicMock()
        
        self.mock_controller.stuck_service = mock_stuck_service
        self.mock_controller.circuit_breaker_service = mock_cb_service
        
        result = await self.service._handle_stuck_detection(self.mock_controller)
        
        self.assertFalse(result)
        mock_cb_service.record_stuck_detection.assert_called_once()

    async def test_handle_stuck_detection_stuck_calls_react_to_exception(self):
        """Test _handle_stuck_detection calls _react_to_exception with AgentStuckInLoopError."""
        from backend.core.exceptions import AgentStuckInLoopError
        
        mock_stuck_service = MagicMock()
        mock_stuck_service.is_stuck.return_value = True
        
        self.mock_controller.stuck_service = mock_stuck_service
        self.mock_controller.circuit_breaker_service = None
        
        result = await self.service._handle_stuck_detection(self.mock_controller)
        
        self.assertFalse(result)
        self.mock_controller._react_to_exception.assert_called_once()
        
        # Verify exception type
        call_args = self.mock_controller._react_to_exception.call_args[0]
        self.assertIsInstance(call_args[0], AgentStuckInLoopError)
        self.assertIn("stuck in a loop", str(call_args[0]))

    async def test_handle_stuck_detection_no_circuit_breaker_service(self):
        """Test _handle_stuck_detection works without circuit breaker service."""
        from backend.core.exceptions import AgentStuckInLoopError
        
        mock_stuck_service = MagicMock()
        mock_stuck_service.is_stuck.return_value = True
        
        self.mock_controller.stuck_service = mock_stuck_service
        self.mock_controller.circuit_breaker_service = None
        
        result = await self.service._handle_stuck_detection(self.mock_controller)
        
        # Should still return False and call _react_to_exception
        self.assertFalse(result)
        self.mock_controller._react_to_exception.assert_called_once()

    async def test_ensure_can_step_both_checks_fail(self):
        """Test ensure_can_step returns False when circuit breaker trips first."""
        # Circuit breaker should be checked first and block
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "Error"
        mock_result.action = "stop"
        mock_result.recommendation = "Fix"
        mock_cb_service.check.return_value = mock_result
        
        mock_stuck_service = MagicMock()
        mock_stuck_service.is_stuck.return_value = True
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        self.mock_controller.stuck_service = mock_stuck_service
        
        result = await self.service.ensure_can_step()
        
        self.assertFalse(result)
        # Circuit breaker trips first, so stuck detection shouldn't be called
        mock_stuck_service.is_stuck.assert_not_called()

    async def test_check_circuit_breaker_none_result(self):
        """Test _check_circuit_breaker handles None result from check."""
        mock_cb_service = MagicMock()
        mock_cb_service.check.return_value = None
        
        self.mock_controller.circuit_breaker_service = mock_cb_service
        
        result = await self.service._check_circuit_breaker(self.mock_controller)
        
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
