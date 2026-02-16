"""Unit tests for backend.review.finish_critic — AgentFinishedCritic."""

from __future__ import annotations


from backend.events.action import PlaybookFinishAction, AgentThinkAction
from backend.events.observation import Observation
from backend.review.finish_critic import AgentFinishedCritic


class TestAgentFinishedCritic:
    """Tests for AgentFinishedCritic evaluation logic."""

    def test_initialization(self):
        """Test critic initialization."""
        critic = AgentFinishedCritic()
        assert critic is not None

    def test_agent_finished_with_finish_action(self):
        """Test successful finish when last action is PlaybookFinishAction."""
        critic = AgentFinishedCritic()
        events = [
            AgentThinkAction(thought="thinking"),
            PlaybookFinishAction(),
        ]

        result = critic.evaluate(events)

        assert result.score == 1
        assert result.message == "Agent finished."
        assert result.success is True

    def test_agent_not_finished_without_finish_action(self):
        """Test failure when last action is not PlaybookFinishAction."""
        critic = AgentFinishedCritic()
        events = [
            AgentThinkAction(thought="thinking"),
            AgentThinkAction(thought="more thinking"),
        ]

        result = critic.evaluate(events)

        assert result.score == 0
        assert result.message == "Agent did not finish."
        assert result.success is False

    def test_agent_finished_with_observations_after(self):
        """Test finish action is found even with observations after it."""
        critic = AgentFinishedCritic()
        events = [
            AgentThinkAction(thought="thinking"),
            PlaybookFinishAction(),
            Observation(content="some output"),
            Observation(content="more output"),
        ]

        result = critic.evaluate(events)

        # The critic should find the last action (PlaybookFinishAction)
        assert result.score == 1
        assert result.message == "Agent finished."
        assert result.success is True

    def test_empty_git_patch(self):
        """Test failure when git patch is empty."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
        ]

        result = critic.evaluate(events, diff_patch="")

        assert result.score == 0
        assert result.message == "Git patch is empty."
        assert result.success is False

    def test_empty_git_patch_whitespace_only(self):
        """Test failure when git patch is only whitespace."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
        ]

        result = critic.evaluate(events, diff_patch="   \n\n   ")

        assert result.score == 0
        assert result.message == "Git patch is empty."
        assert result.success is False

    def test_non_empty_git_patch(self):
        """Test success when git patch has content."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
        ]
        diff = """
diff --git a/file.txt b/file.txt
index 1234567..abcdefg 100644
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 line 1
+new line
 line 2
 line 3
"""

        result = critic.evaluate(events, diff_patch=diff)

        assert result.score == 1
        assert result.message == "Agent finished."
        assert result.success is True

    def test_no_actions_in_events(self):
        """Test failure when there are no actions at all."""
        critic = AgentFinishedCritic()
        events = [
            Observation(content="output 1"),
            Observation(content="output 2"),
        ]

        result = critic.evaluate(events)

        assert result.score == 0
        assert result.message == "Agent did not finish."
        assert result.success is False

    def test_empty_events_list(self):
        """Test failure with empty events list."""
        critic = AgentFinishedCritic()
        events = []

        result = critic.evaluate(events)

        assert result.score == 0
        assert result.message == "Agent did not finish."
        assert result.success is False

    def test_finish_action_not_last(self):
        """Test failure when PlaybookFinishAction is not the last action."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
            AgentThinkAction(thought="later thinking"),
        ]

        result = critic.evaluate(events)

        assert result.score == 0
        assert result.message == "Agent did not finish."
        assert result.success is False

    def test_diff_patch_none(self):
        """Test that None diff_patch doesn't affect evaluation."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
        ]

        result = critic.evaluate(events, diff_patch=None)

        assert result.score == 1
        assert result.message == "Agent finished."
        assert result.success is True

    def test_empty_patch_takes_precedence(self):
        """Test that empty patch causes failure even if agent finished."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
        ]

        result = critic.evaluate(events, diff_patch="  ")

        # Empty patch should be checked first and return 0
        assert result.score == 0
        assert result.message == "Git patch is empty."
        assert result.success is False

    def test_multiple_finish_actions(self):
        """Test with multiple PlaybookFinishActions - last one counts."""
        critic = AgentFinishedCritic()
        events = [
            PlaybookFinishAction(),
            AgentThinkAction(thought="intermediate"),
            PlaybookFinishAction(),
        ]

        result = critic.evaluate(events)

        assert result.score == 1
        assert result.message == "Agent finished."
        assert result.success is True

    def test_critic_result_success_property(self):
        """Test CriticResult success property threshold."""
        critic = AgentFinishedCritic()

        # Success case
        events_success = [PlaybookFinishAction()]
        result_success = critic.evaluate(events_success)
        assert result_success.success is True  # score=1 >= 0.5

        # Failure case
        events_failure = [AgentThinkAction(thought="test")]
        result_failure = critic.evaluate(events_failure)
        assert result_failure.success is False  # score=0 < 0.5
