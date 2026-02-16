"""Tests for backend.review.base and backend.review.finish_critic."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.events.action import PlaybookFinishAction
from backend.review.base import CriticResult
from backend.review.finish_critic import AgentFinishedCritic


# ── CriticResult ───────────────────────────────────────────────────────

class TestCriticResult:
    def test_success_above_threshold(self):
        r = CriticResult(score=0.8, message="ok")
        assert r.success is True

    def test_success_at_threshold(self):
        r = CriticResult(score=0.5, message="ok")
        assert r.success is True

    def test_failure_below_threshold(self):
        r = CriticResult(score=0.4, message="fail")
        assert r.success is False

    def test_zero_score(self):
        r = CriticResult(score=0.0, message="bad")
        assert r.success is False

    def test_full_score(self):
        r = CriticResult(score=1.0, message="perfect")
        assert r.success is True


# ── AgentFinishedCritic ────────────────────────────────────────────────

class TestAgentFinishedCritic:
    def test_empty_patch_returns_zero(self):
        critic = AgentFinishedCritic()
        result = critic.evaluate([], diff_patch="  ")
        assert result.score == 0
        assert "empty" in result.message.lower()

    def test_finish_action_present(self):
        critic = AgentFinishedCritic()
        finish = PlaybookFinishAction(outputs={"content": "done"})
        result = critic.evaluate([finish])
        assert result.score == 1
        assert "finished" in result.message.lower()

    def test_no_finish_action(self):
        critic = AgentFinishedCritic()
        event = MagicMock()
        event.__class__ = type("NotAnAction", (), {})
        result = critic.evaluate([event])
        assert result.score == 0
        assert "did not finish" in result.message.lower()

    def test_finish_action_with_patch(self):
        critic = AgentFinishedCritic()
        finish = PlaybookFinishAction(outputs={"content": "done"})
        result = critic.evaluate([finish], diff_patch="some diff content")
        assert result.score == 1

    def test_empty_events_no_patch(self):
        critic = AgentFinishedCritic()
        result = critic.evaluate([])
        assert result.score == 0
        assert "did not finish" in result.message.lower()

    def test_none_patch_doesnt_trigger_empty_check(self):
        """None patch should not trigger the 'empty patch' check."""
        critic = AgentFinishedCritic()
        result = critic.evaluate([])
        assert "did not finish" in result.message.lower()
