"""Tests for backend.engines.orchestrator.task_complexity.TaskComplexityAnalyzer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.engines.orchestrator.task_complexity import TaskComplexityAnalyzer


# ── helpers ──────────────────────────────────────────────────────────

def _config(**overrides):
    defaults = dict(
        planning_complexity_threshold=3,
        enable_auto_planning=True,
        enable_dynamic_iterations=True,
        min_iterations=20,
        max_iterations_override=500,
        complexity_iteration_multiplier=50.0,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _state(history=None):
    return SimpleNamespace(history=history or [])


# ── analyze_complexity ───────────────────────────────────────────────

class TestAnalyzeComplexity:
    def test_empty_message(self):
        analyzer = TaskComplexityAnalyzer(_config())
        assert analyzer.analyze_complexity("", _state()) == 1.0

    def test_simple_question(self):
        analyzer = TaskComplexityAnalyzer(_config())
        score = analyzer.analyze_complexity("what is the meaning of life", _state())
        assert score == 1.5  # matches simple pattern

    def test_complex_task(self):
        analyzer = TaskComplexityAnalyzer(_config())
        score = analyzer.analyze_complexity(
            "create a new file and refactor the module plus add tests also implement the API",
            _state(),
        )
        # Should be significantly above threshold
        assert score >= 3.0

    def test_action_words_contribute(self):
        analyzer = TaskComplexityAnalyzer(_config())
        score = analyzer.analyze_complexity(
            "implement the feature then test it and deploy",
            _state(),
        )
        assert score > 1.5

    def test_file_mentions_contribute(self):
        analyzer = TaskComplexityAnalyzer(_config())
        score = analyzer.analyze_complexity(
            "edit file main.py and update config.json",
            _state(),
        )
        assert score > 1.0

    def test_capped_at_10(self):
        analyzer = TaskComplexityAnalyzer(_config())
        monster = " and ".join(
            f"create {i} files plus refactor multiple modules" for i in range(20)
        )
        score = analyzer.analyze_complexity(monster, _state())
        assert score == 10.0


# ── _is_simple_task ──────────────────────────────────────────────────

class TestIsSimpleTask:
    def test_simple_patterns(self):
        analyzer = TaskComplexityAnalyzer(_config())
        assert analyzer._is_simple_task("what is the meaning of life")
        assert analyzer._is_simple_task("show me the output")
        assert analyzer._is_simple_task("fix a small typo error")

    def test_complex_not_simple(self):
        analyzer = TaskComplexityAnalyzer(_config())
        assert not analyzer._is_simple_task("create a new module and write tests")


# ── should_plan ──────────────────────────────────────────────────────

class TestShouldPlan:
    def test_disabled(self):
        analyzer = TaskComplexityAnalyzer(_config(enable_auto_planning=False))
        assert not analyzer.should_plan("create everything", _state())

    def test_above_threshold(self):
        analyzer = TaskComplexityAnalyzer(_config(planning_complexity_threshold=2))
        assert analyzer.should_plan(
            "create files and refactor plus test multiple modules", _state()
        )

    def test_below_threshold(self):
        analyzer = TaskComplexityAnalyzer(_config(planning_complexity_threshold=10))
        assert not analyzer.should_plan("fix a typo", _state())


# ── estimate_iterations ──────────────────────────────────────────────

class TestEstimateIterations:
    def test_dynamic_disabled_fallback(self):
        analyzer = TaskComplexityAnalyzer(
            _config(enable_dynamic_iterations=False, max_iterations_override=100)
        )
        assert analyzer.estimate_iterations(5.0, _state()) == 100

    def test_low_complexity(self):
        analyzer = TaskComplexityAnalyzer(_config())
        iters = analyzer.estimate_iterations(1.0, _state())
        assert iters >= 20

    def test_high_complexity(self):
        analyzer = TaskComplexityAnalyzer(_config())
        iters = analyzer.estimate_iterations(10.0, _state())
        assert iters <= 500

    def test_respects_min(self):
        analyzer = TaskComplexityAnalyzer(_config(min_iterations=50))
        iters = analyzer.estimate_iterations(0.1, _state())
        assert iters >= 50
