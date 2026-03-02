"""Tests for StepDecisionService."""

import unittest
from unittest.mock import MagicMock
from typing import Any, cast

from backend.controller.services.step_decision_service import StepDecisionService
from backend.core.schemas import AgentState
from backend.events import EventSource
from backend.events.action import Action, MessageAction
from backend.events.action.agent import CondensationAction, CondensationRequestAction
from backend.events.observation import (
    Observation,
    NullObservation,
    AgentStateChangedObservation,
)
from backend.events.observation.agent import RecallObservation


class TestStepDecisionService(unittest.TestCase):
    """Test StepDecisionService step decision logic."""

    def setUp(self):
        """Create mock controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.get_agent_state = MagicMock(
            return_value=AgentState.RUNNING
        )

        self.service = StepDecisionService(self.mock_controller)

    def test_should_step_message_from_user(self):
        """Test should_step returns True for user messages."""
        action = MessageAction(content="Hello")
        action.source = EventSource.USER

        result = self.service.should_step(action)

        self.assertTrue(result)

    def test_should_step_message_from_agent_running(self):
        """Test should_step returns True for agent message when running."""
        action = MessageAction(content="Response")
        action.source = EventSource.AGENT
        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING

        result = self.service.should_step(action)

        self.assertTrue(result)

    def test_should_step_message_from_agent_awaiting_input(self):
        """Test should_step returns False for agent message when awaiting input."""
        action = MessageAction(content="Question")
        action.source = EventSource.AGENT
        self.mock_controller.get_agent_state.return_value = (
            AgentState.AWAITING_USER_INPUT
        )

        result = self.service.should_step(action)

        self.assertFalse(result)

    def test_should_step_message_from_agent_paused(self):
        """Test should_step returns True for agent message when paused."""
        action = MessageAction(content="Info")
        action.source = EventSource.AGENT
        self.mock_controller.get_agent_state.return_value = AgentState.PAUSED

        result = self.service.should_step(action)

        self.assertTrue(result)

    def test_should_step_condensation_action(self):
        """Test should_step returns True for CondensationAction."""
        action = MagicMock(spec=CondensationAction)

        result = self.service.should_step(action)

        self.assertTrue(result)

    def test_should_step_condensation_request_action(self):
        """Test should_step returns True for CondensationRequestAction."""
        action = MagicMock(spec=CondensationRequestAction)

        result = self.service.should_step(action)

        self.assertTrue(result)

    def test_should_step_other_action(self):
        """Test should_step returns False for other actions."""
        action = MagicMock(spec=Action)

        result = self.service.should_step(action)

        self.assertFalse(result)

    def test_should_step_null_observation_with_cause(self):
        """Test should_step returns True for NullObservation with cause."""
        observation = NullObservation(content="")
        observation.cause = 123

        result = self.service.should_step(observation)

        self.assertTrue(result)

    def test_should_step_null_observation_without_cause(self):
        """Test should_step returns False for NullObservation without cause."""
        observation = NullObservation(content="")
        observation.cause = None

        result = self.service.should_step(observation)

        self.assertFalse(result)

    def test_should_step_null_observation_empty_cause(self):
        """Test should_step returns False for NullObservation with empty cause."""
        observation = NullObservation(content="")
        observation.cause = 0

        result = self.service.should_step(observation)

        self.assertFalse(result)

    def test_should_step_agent_state_changed_observation(self):
        """Test should_step returns False for AgentStateChangedObservation."""
        observation = AgentStateChangedObservation(
            content="State changed", agent_state=AgentState.RUNNING, reason=""
        )

        result = self.service.should_step(observation)

        self.assertFalse(result)

    def test_should_step_recall_observation(self):
        """Test should_step returns False for RecallObservation."""
        observation = MagicMock(spec=RecallObservation)

        result = self.service.should_step(observation)

        self.assertFalse(result)

    def test_should_step_regular_observation(self):
        """Test should_step returns True for regular observations."""
        observation = MagicMock(spec=Observation)

        result = self.service.should_step(observation)

        self.assertTrue(result)

    def test_should_step_non_event(self):
        """Test should_step returns False for non-event objects."""
        result = self.service.should_step(cast(Any, "not an event"))

        self.assertFalse(result)

    def test_should_step_none(self):
        """Test should_step returns False for None."""
        result = self.service.should_step(cast(Any, None))

        self.assertFalse(result)

    def test_for_action_delegation(self):
        """Test _for_action delegates to specific handlers."""
        action = MessageAction(content="Test")
        action.source = EventSource.USER

        # Should delegate to message handler
        result = self.service._for_action(action)
        self.assertTrue(result)

    def test_for_message_action_user_always_steps(self):
        """Test _for_message_action always steps for user messages."""
        action = MessageAction(content="Test")
        action.source = EventSource.USER

        # Should always return True regardless of state
        self.mock_controller.get_agent_state.return_value = (
            AgentState.AWAITING_USER_INPUT
        )
        result = self.service._for_message_action(action)
        self.assertTrue(result)

        self.mock_controller.get_agent_state.return_value = AgentState.RUNNING
        result = self.service._for_message_action(action)
        self.assertTrue(result)

    def test_for_observation_delegates_to_handlers(self):
        """Test _for_observation delegates based on observation type."""
        # Regular observation
        obs = MagicMock(spec=Observation)
        self.assertTrue(self.service._for_observation(obs))

        # StateChanged observation
        state_obs = AgentStateChangedObservation(
            content="", agent_state=AgentState.RUNNING, reason=""
        )
        self.assertFalse(self.service._for_observation(state_obs))


if __name__ == "__main__":
    unittest.main()
