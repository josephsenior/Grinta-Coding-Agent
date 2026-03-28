"""Tests for StepPrerequisiteService."""

import unittest
from unittest.mock import MagicMock

from backend.orchestration.services.step_prerequisite_service import (
    StepPrerequisiteService,
)
from backend.core.schemas import AgentState
from backend.ledger import RecallType
from backend.ledger.action.agent import RecallAction


class TestStepPrerequisiteService(unittest.TestCase):
    """Test StepPrerequisiteService prerequisite checks."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.mock_controller = MagicMock()
        self.mock_controller.get_agent_state = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.mock_context.pending_action = None

        self.service = StepPrerequisiteService(self.mock_context)

    def test_can_step_when_running_no_pending(self):
        """Test can_step returns True when running with no pending action."""
        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING
        self.mock_context.pending_action = None

        result = self.service.can_step()

        self.assertTrue(result)

    def test_can_step_blocked_by_state(self):
        """Test can_step returns False when not in RUNNING state."""
        self.mock_controller.get_agent_state.return_value = AgentState.PAUSED
        self.mock_context.pending_action = None

        result = self.service.can_step()

        self.assertFalse(result)

        # Should log the block reason
        self.mock_controller.log.assert_called_once()
        call_args = self.mock_controller.log.call_args[0]
        self.assertEqual(call_args[0], "debug")
        self.assertIn("PAUSED", call_args[1])

    def test_can_step_blocked_by_state_finished(self):
        """Test can_step returns False when state is FINISHED."""
        self.mock_controller.get_agent_state.return_value = AgentState.FINISHED
        self.mock_context.pending_action = None

        result = self.service.can_step()

        self.assertFalse(result)

    def test_can_step_blocked_by_state_stopped(self):
        """Test can_step returns False when state is STOPPED."""
        self.mock_controller.get_agent_state.return_value = AgentState.STOPPED
        self.mock_context.pending_action = None

        result = self.service.can_step()

        self.assertFalse(result)

    def test_can_step_blocked_by_pending_action(self):
        """Test can_step returns False when there's a pending action."""
        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING

        mock_pending = MagicMock()
        mock_pending.id = "action-123"
        self.mock_context.pending_action = mock_pending

        result = self.service.can_step()

        self.assertFalse(result)

        # Should log pending action info
        self.mock_controller.log.assert_called_once()
        call_args = self.mock_controller.log.call_args[0]
        self.assertIn("action-123", call_args[1])

    def test_can_step_pending_action_no_id(self):
        """Test can_step handles pending action without id attribute."""
        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING

        mock_pending = MagicMock(spec=[])  # No id attribute
        self.mock_context.pending_action = mock_pending

        result = self.service.can_step()

        self.assertFalse(result)

        # Should log with 'unknown' id
        call_args = self.mock_controller.log.call_args[0]
        self.assertIn("unknown", call_args[1])

    def test_can_step_allows_pending_recall_action(self):
        """Recall actions should not block the main step path."""
        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING
        self.mock_context.pending_action = RecallAction(
            query="q", recall_type=RecallType.KNOWLEDGE
        )

        result = self.service.can_step()

        self.assertTrue(result)
        call_kwargs = self.mock_controller.log.call_args[1]
        self.assertEqual(call_kwargs["extra"]["msg_type"], "STEP_ALLOWED_PENDING_RECALL")

    def test_can_step_log_message_type_state(self):
        """Test can_step logs correct message type for state block."""
        self.mock_controller.get_agent_state.return_value = AgentState.ERROR

        self.service.can_step()

        # Should use STEP_BLOCKED_STATE message type
        call_kwargs = self.mock_controller.log.call_args[1]
        self.assertEqual(call_kwargs["extra"]["msg_type"], "STEP_BLOCKED_STATE")

    def test_can_step_log_message_type_pending(self):
        """Test can_step logs correct message type for pending action block."""
        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING
        self.mock_context.pending_action = MagicMock()

        self.service.can_step()

        # Should use STEP_BLOCKED_PENDING_ACTION message type
        call_kwargs = self.mock_controller.log.call_args[1]
        self.assertEqual(
            call_kwargs["extra"]["msg_type"], "STEP_BLOCKED_PENDING_ACTION"
        )

    def test_can_step_multiple_blocks_state_first(self):
        """Test can_step checks state before pending action."""
        self.mock_controller.get_agent_state.return_value = AgentState.LOADING
        self.mock_context.pending_action = MagicMock()

        result = self.service.can_step()

        self.assertFalse(result)

        # Should log state block (not pending action)
        call_kwargs = self.mock_controller.log.call_args[1]
        self.assertEqual(call_kwargs["extra"]["msg_type"], "STEP_BLOCKED_STATE")

    def test_can_step_awaiting_user_input(self):
        """Test can_step returns False when awaiting user input."""
        self.mock_controller.get_agent_state.return_value = (
            AgentState.AWAITING_USER_INPUT
        )

        result = self.service.can_step()

        self.assertFalse(result)

    def test_can_step_awaiting_confirmation(self):
        """Test can_step returns False when awaiting confirmation."""
        self.mock_controller.get_agent_state.return_value = (
            AgentState.AWAITING_USER_CONFIRMATION
        )

        result = self.service.can_step()

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
