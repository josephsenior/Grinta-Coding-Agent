"""Tests for backend.review.base and backend.review.finish_critic."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.review.base import BaseCritic, CriticResult


# ── CriticResult ─────────────────────────────────────────────────────


class TestCriticResult:
    def test_score_and_message(self):
        r = CriticResult(score=0.8, message="Good")
        assert r.score == 0.8
        assert r.message == "Good"

    def test_success_above_threshold(self):
        assert CriticResult(score=0.5, message="ok").success is True
        assert CriticResult(score=1.0, message="perfect").success is True

    def test_success_below_threshold(self):
        assert CriticResult(score=0.0, message="fail").success is False
        assert CriticResult(score=0.49, message="close").success is False

    def test_success_boundary(self):
        assert CriticResult(score=0.5, message="boundary").success is True

    def test_zero_score(self):
        r = CriticResult(score=0, message="")
        assert r.success is False

    def test_negative_score(self):
        r = CriticResult(score=-1.0, message="bad")
        assert r.success is False


# ── BaseCritic ───────────────────────────────────────────────────────


class TestBaseCritic:
    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseCritic()  # type: ignore

    def test_concrete_subclass(self):
        class MyCritic(BaseCritic):
            def evaluate(self, events, diff_patch=None):
                return CriticResult(score=1.0, message="done")

        c = MyCritic()
        result = c.evaluate([])
        assert result.score == 1.0


# ── AgentFinishedCritic ──────────────────────────────────────────────


class TestAgentFinishedCritic:
    @pytest.fixture()
    def critic(self):
        from backend.review.finish_critic import AgentFinishedCritic

        return AgentFinishedCritic()

    def _make_finish_action(self):
        from backend.events.action import PlaybookFinishAction

        return PlaybookFinishAction()

    def _make_other_action(self):
        from backend.events.action import Action

        mock = MagicMock(spec=Action)
        # Ensure isinstance(mock, Action) is True
        cast(Any, mock).__class__ = Action
        return mock

    def test_agent_finished(self, critic):
        finish = self._make_finish_action()
        result = critic.evaluate([finish])
        assert result.score == 1

    def test_agent_not_finished(self, critic):
        # An event that is NOT a PlaybookFinishAction
        non_action = MagicMock()
        result = critic.evaluate([non_action])
        assert result.score == 0
        assert (
            "task incomplete" in result.message.lower()
            or "suboptimal exit" in result.message.lower()
        )

    def test_empty_events(self, critic):
        result = critic.evaluate([])
        assert result.score == 0

    def test_empty_diff_patch(self, critic):
        finish = self._make_finish_action()
        result = critic.evaluate([finish], diff_patch="")
        assert result.score == 0

    def test_whitespace_diff_patch(self, critic):
        finish = self._make_finish_action()
        result = critic.evaluate([finish], diff_patch="  \n  ")
        assert result.score == 0

    def test_valid_diff_patch_and_finish(self, critic):
        finish = self._make_finish_action()
        result = critic.evaluate([finish], diff_patch="--- a/file\n+++ b/file")
        assert result.score == 1

    def test_none_diff_patch_still_checks_finish(self, critic):
        finish = self._make_finish_action()
        result = critic.evaluate([finish], diff_patch=None)
        assert result.score == 1
