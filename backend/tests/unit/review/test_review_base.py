"""Tests for backend.review.base — CriticResult and BaseCritic."""

from __future__ import annotations

import pytest

from backend.review.base import BaseCritic, CriticResult


# ── CriticResult ──────────────────────────────────────────────────────


class TestCriticResult:
    def test_construction(self):
        r = CriticResult(score=0.8, message="good job")
        assert r.score == 0.8
        assert r.message == "good job"

    def test_success_above_threshold(self):
        assert CriticResult(score=0.5, message="").success is True
        assert CriticResult(score=0.7, message="").success is True
        assert CriticResult(score=1.0, message="").success is True

    def test_failure_below_threshold(self):
        assert CriticResult(score=0.0, message="bad").success is False
        assert CriticResult(score=0.49, message="bad").success is False

    def test_exact_threshold(self):
        assert CriticResult(score=0.5, message="boundary").success is True

    def test_pydantic_model(self):
        r = CriticResult(score=0.9, message="ok")
        d = r.model_dump()
        assert d["score"] == 0.9
        assert d["message"] == "ok"

    def test_json_round_trip(self):
        r = CriticResult(score=0.75, message="round trip")
        json_str = r.model_dump_json()
        r2 = CriticResult.model_validate_json(json_str)
        assert r2.score == r.score
        assert r2.message == r.message


# ── BaseCritic ────────────────────────────────────────────────────────


class TestBaseCritic:
    def test_is_abstract(self):
        with pytest.raises(TypeError, match="abstract"):
            BaseCritic()  # type: ignore[abstract]

    def test_concrete_implementation(self):
        class MyCritic(BaseCritic):
            def evaluate(self, events, diff_patch=None):
                return CriticResult(score=1.0, message="perfect")

        critic = MyCritic()
        result = critic.evaluate([], None)
        assert result.success is True
        assert result.score == 1.0

    def test_evaluate_with_events_and_diff(self):
        class DiffCritic(BaseCritic):
            def evaluate(self, events, diff_patch=None):
                score = 0.8 if diff_patch else 0.3
                return CriticResult(score=score, message=f"events={len(events)}")

        critic = DiffCritic()
        r1 = critic.evaluate([1, 2, 3], diff_patch="--- a/f\n+++ b/f\n")
        assert r1.score == 0.8
        assert "events=3" in r1.message

        r2 = critic.evaluate([], diff_patch=None)
        assert r2.score == 0.3
