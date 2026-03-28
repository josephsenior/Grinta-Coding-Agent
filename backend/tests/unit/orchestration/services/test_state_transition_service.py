"""Tests for StateTransitionService."""

import unittest
from unittest.mock import MagicMock, patch

from backend.orchestration.services.state_transition_service import (
    StateTransitionService,
    InvalidStateTransitionError,
    VALID_TRANSITIONS,
)
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import ActionConfirmationStatus


class TestStateTransitionService(unittest.IsolatedAsyncioTestCase):
    """Test StateTransitionService state transition logic."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.mock_context.controller_name = "TestAgent"
        self.mock_context.state = MagicMock()
        self.mock_context.state.agent_state = AgentState.LOADING
        self.mock_context.state.last_error = ""
        self.mock_context.event_stream = MagicMock()
        self.mock_context.pending_action = None
        self.mock_context.state_tracker = MagicMock()
        self.mock_context.headless_mode = False

        self.service = StateTransitionService(self.mock_context)

    async def test_set_agent_state_same_state(self):
        """Test set_agent_state with same state does nothing."""
        self.mock_context.state.agent_state = AgentState.RUNNING

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should not process transition
        self.mock_context.state.set_agent_state.assert_not_called()

    async def test_set_agent_state_valid_transition(self):
        """Test set_agent_state with valid transition."""
        self.mock_context.state.agent_state = AgentState.LOADING

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should set new state
        self.mock_context.state.set_agent_state.assert_called_once_with(
            AgentState.RUNNING, source="StateTransitionService.set_agent_state"
        )

        # Should emit state changed event
        self.mock_context.event_stream.add_event.assert_called_once()

        # Should save state
        self.mock_context.save_state.assert_called_once()

    async def test_set_agent_state_invalid_transition(self):
        """Test set_agent_state raises error for invalid transition."""
        self.mock_context.state.agent_state = AgentState.FINISHED

        with self.assertRaises(InvalidStateTransitionError) as ctx:
            await self.service.set_agent_state(AgentState.PAUSED)

        # Should contain error details (state values are lowercase)
        self.assertIn("finished", str(ctx.exception))
        self.assertIn("paused", str(ctx.exception))

    async def test_set_agent_state_to_error_with_reason(self):
        """Test set_agent_state to ERROR includes error reason."""
        self.mock_context.state.agent_state = AgentState.RUNNING
        self.mock_context.state.last_error = "Connection timeout"

        await self.service.set_agent_state(AgentState.ERROR)

        # Should include reason in observation (content is empty, reason has error)
        call_args = self.mock_context.event_stream.add_event.call_args
        observation = call_args[0][0]
        self.assertEqual(observation.reason, "Connection timeout")

    async def test_set_agent_state_to_stopped_resets_controller(self):
        """Test set_agent_state to STOPPED resets controller."""
        self.mock_context.state.agent_state = AgentState.RUNNING

        await self.service.set_agent_state(AgentState.STOPPED)

        # Should reset controller
        self.mock_context.reset_controller.assert_called_once()

    async def test_set_agent_state_to_error_resets_controller(self):
        """Test set_agent_state to ERROR resets controller."""
        self.mock_context.state.agent_state = AgentState.RUNNING

        await self.service.set_agent_state(AgentState.ERROR)

        # Should reset controller
        self.mock_context.reset_controller.assert_called_once()

    async def test_set_agent_state_error_recovery(self):
        """Test set_agent_state from ERROR to RUNNING increases limits."""
        self.mock_context.state.agent_state = AgentState.ERROR

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should increase control flags limits
        self.mock_context.state_tracker.maybe_increase_control_flags_limits.assert_called_once_with(
            False
        )

    async def test_set_agent_state_error_recovery_headless(self):
        """Test set_agent_state error recovery in headless mode."""
        self.mock_context.state.agent_state = AgentState.ERROR
        self.mock_context.headless_mode = True

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should pass headless mode flag
        self.mock_context.state_tracker.maybe_increase_control_flags_limits.assert_called_once_with(
            True
        )

    async def test_set_agent_state_no_error_recovery_for_other_states(self):
        """Test set_agent_state doesn't trigger error recovery for non-ERROR states."""
        self.mock_context.state.agent_state = AgentState.PAUSED

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should not call error recovery
        self.mock_context.state_tracker.maybe_increase_control_flags_limits.assert_not_called()

    async def test_set_agent_state_user_confirmed_emits_pending(self):
        """Test set_agent_state to USER_CONFIRMED emits pending action."""
        self.mock_context.state.agent_state = AgentState.AWAITING_USER_CONFIRMATION

        mock_pending = MagicMock()
        mock_pending.thought = "Test thought"
        mock_pending._id = "action-123"
        self.mock_context.pending_action = mock_pending

        await self.service.set_agent_state(AgentState.USER_CONFIRMED)

        # Should clear thought and set confirmation state
        self.assertEqual(mock_pending.thought, "")
        self.assertEqual(
            mock_pending.confirmation_state, ActionConfirmationStatus.CONFIRMED
        )
        self.assertIsNone(mock_pending._id)

        # Should emit action
        self.mock_context.emit_event.assert_called_with(mock_pending, EventSource.AGENT)

        # Should clear pending action
        self.mock_context.clear_pending_action.assert_called_once()

    async def test_set_agent_state_user_rejected_emits_pending(self):
        """Test set_agent_state to USER_REJECTED emits pending action."""
        self.mock_context.state.agent_state = AgentState.AWAITING_USER_CONFIRMATION

        mock_pending = MagicMock()
        mock_pending.thought = "Thought"
        mock_pending._id = "action-456"
        self.mock_context.pending_action = mock_pending

        await self.service.set_agent_state(AgentState.USER_REJECTED)

        # Should set rejected state
        self.assertEqual(
            mock_pending.confirmation_state, ActionConfirmationStatus.REJECTED
        )

        # Should emit and clear
        self.mock_context.emit_event.assert_called()
        self.mock_context.clear_pending_action.assert_called_once()

    async def test_set_agent_state_no_pending_action(self):
        """Test set_agent_state when no pending action."""
        self.mock_context.state.agent_state = AgentState.AWAITING_USER_CONFIRMATION
        self.mock_context.pending_action = None

        await self.service.set_agent_state(AgentState.USER_CONFIRMED)

        # Should not emit pending action
        self.mock_context.clear_pending_action.assert_not_called()

    async def test_set_agent_state_pending_action_no_thought(self):
        """Test set_agent_state with pending action lacking thought attribute."""
        self.mock_context.state.agent_state = AgentState.AWAITING_USER_CONFIRMATION

        mock_pending = MagicMock(spec=["_id", "confirmation_state"])
        mock_pending._id = "action-789"
        self.mock_context.pending_action = mock_pending

        await self.service.set_agent_state(AgentState.USER_CONFIRMED)

        # Should still process without thought
        self.mock_context.emit_event.assert_called()

    async def test_set_agent_state_from_loading_to_running(self):
        """Test valid transition from LOADING to RUNNING."""
        self.mock_context.state.agent_state = AgentState.LOADING

        await self.service.set_agent_state(AgentState.RUNNING)

        self.mock_context.state.set_agent_state.assert_called_once()

    async def test_set_agent_state_from_running_to_paused(self):
        """Test valid transition from RUNNING to PAUSED."""
        self.mock_context.state.agent_state = AgentState.RUNNING

        await self.service.set_agent_state(AgentState.PAUSED)

        self.mock_context.state.set_agent_state.assert_called_once()

    async def test_set_agent_state_from_paused_to_running(self):
        """Test valid transition from PAUSED to RUNNING."""
        self.mock_context.state.agent_state = AgentState.PAUSED

        await self.service.set_agent_state(AgentState.RUNNING)

        self.mock_context.state.set_agent_state.assert_called_once()

    async def test_set_agent_state_event_source(self):
        """Test set_agent_state emits event with ENVIRONMENT source."""
        self.mock_context.state.agent_state = AgentState.LOADING

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should use ENVIRONMENT source
        call_args = self.mock_context.event_stream.add_event.call_args[0]
        self.assertEqual(call_args[1], EventSource.ENVIRONMENT)

    @patch("backend.orchestration.services.state_transition_service.logger")
    async def test_set_agent_state_logs_transition(self, mock_logger):
        """Test set_agent_state logs the transition."""
        self.mock_context.state.agent_state = AgentState.LOADING

        await self.service.set_agent_state(AgentState.RUNNING)

        # Should log info message
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        self.assertIn("TestAgent", call_args[1])

    @patch("backend.orchestration.services.state_transition_service.logger")
    async def test_set_agent_state_logs_invalid_transition(self, mock_logger):
        """Test set_agent_state logs warning for invalid transition."""
        self.mock_context.state.agent_state = AgentState.FINISHED

        with self.assertRaises(InvalidStateTransitionError):
            await self.service.set_agent_state(AgentState.PAUSED)

        # Should log warning
        mock_logger.warning.assert_called_once()

    def test_valid_transitions_completeness(self):
        """Test VALID_TRANSITIONS defines all agent states."""
        all_states = set(AgentState)
        defined_states = set(VALID_TRANSITIONS.keys())

        # All states should have defined transitions
        self.assertEqual(all_states, defined_states)


class TestInvalidStateTransitionError(unittest.TestCase):
    """Test InvalidStateTransitionError exception."""

    def test_exception_attributes(self):
        """Test exception stores state information."""
        exc = InvalidStateTransitionError(
            AgentState.FINISHED, AgentState.PAUSED, "TestAgent"
        )

        self.assertEqual(exc.old_state, AgentState.FINISHED)
        self.assertEqual(exc.new_state, AgentState.PAUSED)
        self.assertIn("finished", str(exc))
        self.assertIn("paused", str(exc))
        self.assertIn("TestAgent", str(exc))


if __name__ == "__main__":
    unittest.main()
