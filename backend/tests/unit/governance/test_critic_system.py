"""Tests for backend.governance — critic system for scoring agent runs."""

from typing import cast
from unittest.mock import MagicMock

import pytest

from backend.governance import AgentFinishedCritic
from backend.governance.base import BaseCritic, CriticResult
from backend.ledger.action import Action, PlaybookFinishAction
from backend.ledger.event import Event
from backend.ledger.observation import Observation


class TestCriticResult:
    """Tests for CriticResult Pydantic model."""

    def test_create_critic_result(self):
        """Test creating CriticResult instance."""
        result = CriticResult(score=0.8, message='Good work')
        assert result.score == 0.8

    def test_success_property_true(self):
        """Test success property returns True for score >= 0.5."""
        result = CriticResult(score=0.5, message='')
        assert result.success is True

        result = CriticResult(score=0.9, message='')
        assert result.success is True

        result = CriticResult(score=1.0, message='')
        assert result.success is True

    def test_success_property_false(self):
        """Test success property returns False for score < 0.5."""
        result = CriticResult(score=0.49, message='')
        assert result.success is False

        result = CriticResult(score=0.0, message='')
        assert result.success is False

        result = CriticResult(score=0.3, message='')
        assert result.success is False

    def test_success_exact_threshold(self):
        """Test success property at exact 0.5 threshold."""
        result = CriticResult(score=0.5, message='Exactly at threshold')
        assert result.success is True

    def test_critic_result_with_various_messages(self):
        """Test CriticResult with different message types."""
        result1 = CriticResult(score=1.0, message='Success')
        result2 = CriticResult(score=0.0, message='Failed')
        result3 = CriticResult(score=0.5, message='')

        assert result1.message == 'Success'
        assert result2.message == 'Failed'
        assert result3.message == ''

    def test_critic_result_is_pydantic_model(self):
        """Test CriticResult is a Pydantic BaseModel."""
        from pydantic import BaseModel

        result = CriticResult(score=0.7, message='Test')
        assert isinstance(result, BaseModel)

    def test_critic_result_serialization(self):
        """Test CriticResult can be serialized."""
        result = CriticResult(score=0.8, message='Test message')
        data = result.model_dump()
        assert data['score'] == 0.8
        assert data['message'] == 'Test message'

    def test_critic_result_score_types(self):
        """Test CriticResult accepts different score numeric types."""
        result_int = CriticResult(score=1, message='Integer score')
        result_float = CriticResult(score=0.75, message='Float score')

        assert result_int.score == 1.0
        assert result_float.score == 0.75


class TestBaseCritic:
    """Tests for BaseCritic abstract base class."""

    def test_cannot_instantiate_base_critic(self):
        """Test BaseCritic cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseCritic()  # type: ignore

    def test_has_evaluate_method(self):
        """Test BaseCritic has abstract evaluate method."""
        assert hasattr(BaseCritic, 'evaluate')

    def test_subclass_must_implement_evaluate(self):
        """Test subclass must implement evaluate method."""

        class IncompleteCritic(BaseCritic):
            pass

        with pytest.raises(TypeError):
            IncompleteCritic()  # type: ignore

    def test_valid_subclass_implementation(self):
        """Test valid BaseCritic subclass implementation."""

        class ValidCritic(BaseCritic):
            def evaluate(self, events, diff_patch=None):
                return CriticResult(score=1.0, message='Valid')

        critic = ValidCritic()
        assert isinstance(critic, BaseCritic)
        result = critic.evaluate([])
        assert isinstance(result, CriticResult)


class TestAgentFinishedCritic:
    """Tests for AgentFinishedCritic class."""

    def test_create_agent_finished_critic(self):
        """Test creating AgentFinishedCritic instance."""
        critic = AgentFinishedCritic()
        assert isinstance(critic, BaseCritic)
        assert isinstance(critic, AgentFinishedCritic)

    def test_evaluate_with_finish_action(self):
        """Test evaluate returns success when last action is PlaybookFinishAction."""
        critic = AgentFinishedCritic()
        finish_action = PlaybookFinishAction(outputs={})
        events = [finish_action]

        result = critic.evaluate(events)

        assert result.score == 1.0
        assert result.success is True

    def test_evaluate_without_finish_action(self):
        """Test evaluate returns failure when last action is not PlaybookFinishAction."""
        critic = AgentFinishedCritic()
        regular_action = MagicMock(spec=Action)
        events = [regular_action]

        result = critic.evaluate(events)

        assert result.score == 0.0
        assert result.success is False

    def test_evaluate_empty_events_list(self):
        """Test evaluate with empty events list."""
        critic = AgentFinishedCritic()
        result = critic.evaluate([])

        assert result.score == 0.0
        assert result.success is False

    def test_evaluate_with_empty_git_patch(self):
        """Test evaluate returns failure when git patch is empty."""
        critic = AgentFinishedCritic()
        finish_action = PlaybookFinishAction(outputs={})
        events = [finish_action]

        result = critic.evaluate(events, diff_patch='')

        assert result.score == 0.0
        assert result.success is False

    def test_evaluate_with_whitespace_git_patch(self):
        """Test evaluate handles whitespace-only git patch."""
        critic = AgentFinishedCritic()
        finish_action = PlaybookFinishAction(outputs={})
        events = [finish_action]

        result = critic.evaluate(events, diff_patch='   \n  \t  ')

        assert result.score == 0.0
        assert result.success is False

    def test_evaluate_with_valid_git_patch(self):
        """Test evaluate succeeds with valid git patch."""
        critic = AgentFinishedCritic()
        finish_action = PlaybookFinishAction(outputs={})
        events = [finish_action]

        git_patch = """
diff --git a/file.py b/file.py
index 1234567..89abcdef 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
+def new_function():
+    pass
"""

        result = critic.evaluate(events, diff_patch=git_patch)

        assert result.score == 1.0
        assert result.success is True

    def test_evaluate_with_multiple_actions(self):
        """Test evaluate finds PlaybookFinishAction even with multiple actions."""
        critic = AgentFinishedCritic()
        action1 = MagicMock(spec=Action)
        action2 = MagicMock(spec=Action)
        finish_action = PlaybookFinishAction(outputs={})

        events = cast(list[Event], [action1, action2, finish_action])

        result = critic.evaluate(events)

        assert result.score == 1.0
        assert result.success is True

    def test_evaluate_with_observations_between_actions(self):
        """Test evaluate handles observations mixed with actions."""
        critic = AgentFinishedCritic()
        action1 = MagicMock(spec=Action)
        obs1 = MagicMock(spec=Observation)
        finish_action = PlaybookFinishAction(outputs={})
        obs2 = MagicMock(spec=Observation)

        events = cast(list[Event], [action1, obs1, finish_action, obs2])

        result = critic.evaluate(events)

        # Last action is finish_action (ignoring observations)
        assert result.score == 1.0
        assert result.success is True

    def test_evaluate_finish_not_last_event(self):
        """Test evaluate when finish action is not last event but is last action."""
        critic = AgentFinishedCritic()
        finish_action = PlaybookFinishAction(outputs={})
        obs = MagicMock(spec=Observation)

        # Finish action followed by observation
        events = cast(list[Event], [finish_action, obs, obs])

        result = critic.evaluate(events)

        assert result.score == 1.0
        assert result.success is True

    def test_evaluate_no_actions_only_observations(self):
        """Test evaluate when events contain only observations."""
        critic = AgentFinishedCritic()
        obs1 = MagicMock(spec=Observation)
        obs2 = MagicMock(spec=Observation)

        events = cast(list[Event], [obs1, obs2])

        result = critic.evaluate(events)

        assert result.score == 0.0
        assert result.success is False

    def test_evaluate_none_diff_patch(self):
        """Test evaluate with None diff_patch (default)."""
        critic = AgentFinishedCritic()
        finish_action = PlaybookFinishAction(outputs={})
        events = [finish_action]

        result = critic.evaluate(events, diff_patch=None)

        # Should succeed without checking patch
        assert result.score == 1.0
        assert result.success is True

    def test_multiple_evaluations(self):
        """Test critic can be reused for multiple evaluations."""
        critic = AgentFinishedCritic()

        # First evaluation - success
        events1 = [PlaybookFinishAction(outputs={})]
        result1 = critic.evaluate(events1)
        assert result1.success is True

        # Second evaluation - failure
        action2 = MagicMock(spec=Action)
        events2 = [action2]
        result2 = critic.evaluate(events2)
        assert result2.success is False

        # Third evaluation - success again
        events3 = [PlaybookFinishAction(outputs={})]
        result3 = critic.evaluate(events3)
        assert result3.success is True


class TestCriticIntegration:
    """Integration tests for critic system."""

    def test_critic_result_success_threshold_boundary(self):
        """Test CriticResult success boundary cases."""
        # Just below threshold
        result_below = CriticResult(score=0.4999, message='')
        assert result_below.success is False

        # Exactly at threshold
        result_at = CriticResult(score=0.5, message='')
        assert result_at.success is True

        # Just above threshold
        result_above = CriticResult(score=0.5001, message='')
        assert result_above.success is True

    def test_agent_finished_critic_comprehensive_scenario(self):
        """Test comprehensive scenario with AgentFinishedCritic."""
        critic = AgentFinishedCritic()

        # Scenario 1: Agent finished with changes
        finish = PlaybookFinishAction(outputs={})
        patch = '+def new_function():\n+    pass'
        result = critic.evaluate([finish], diff_patch=patch)
        assert result.success is True
        assert result.score == 1.0

        # Scenario 2: Agent finished but no changes
        result = critic.evaluate([finish], diff_patch='')
        assert result.success is False
        assert result.score == 0.0

        # Scenario 3: Agent didn't finish
        action = MagicMock(spec=Action)
        result = critic.evaluate([action], diff_patch=patch)
        assert result.success is False
        assert result.score == 0.0

    def test_multiple_critics_different_results(self):
        """Test that different critic instances produce independent results."""
        critic1 = AgentFinishedCritic()
        critic2 = AgentFinishedCritic()

        finish = PlaybookFinishAction(outputs={})
        action = MagicMock(spec=Action)

        result1 = critic1.evaluate([finish])
        result2 = critic2.evaluate([action])

        assert result1.success is True
        assert result2.success is False
        # Critics should be independent
        assert critic1 is not critic2
