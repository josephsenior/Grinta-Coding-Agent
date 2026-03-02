"""Comprehensive unit tests for TaskComplexityAnalyzer.

TaskComplexityAnalyzer is pure-logic (regex + config attributes), so all
methods can be tested without mocking external services.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from typing import cast

import pytest

from backend.controller.state.state import State
from backend.engines.orchestrator.task_complexity import TaskComplexityAnalyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(
    threshold: float = 3.0,
    enable_auto_planning: bool = True,
    enable_dynamic_iterations: bool = True,
    min_iterations: int = 20,
    max_iterations_override: int | None = 500,
    complexity_iteration_multiplier: float = 50.0,
) -> MagicMock:
    cfg = MagicMock()
    cfg.planning_complexity_threshold = threshold
    cfg.enable_auto_planning = enable_auto_planning
    cfg.enable_dynamic_iterations = enable_dynamic_iterations
    cfg.min_iterations = min_iterations
    cfg.max_iterations_override = max_iterations_override
    cfg.complexity_iteration_multiplier = complexity_iteration_multiplier
    return cfg


def _state(history=None) -> MagicMock:
    s = MagicMock()
    s.history = history or []
    return s


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_stores_config(self):
        cfg = _config()
        analyzer = TaskComplexityAnalyzer(cfg)
        assert analyzer._config is cfg

    def test_default_threshold_from_config(self):
        cfg = _config(threshold=5.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        assert analyzer._threshold == 5.0

    def test_threshold_default_when_attribute_missing(self):
        cfg = MagicMock(spec=[])  # no attributes
        analyzer = TaskComplexityAnalyzer(cfg)
        assert analyzer._threshold == 3  # getattr default


# ---------------------------------------------------------------------------
# analyze_complexity
# ---------------------------------------------------------------------------

class TestAnalyzeComplexity:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())
        self.state = _state()

    def test_empty_message_returns_1(self):
        assert self.analyzer.analyze_complexity("", self.state) == 1.0

    def test_whitespace_message_returns_1(self):
        assert self.analyzer.analyze_complexity("   ", self.state) == 1.0

    def test_simple_question_returns_low_score(self):
        score = self.analyzer.analyze_complexity("what is this code doing?", self.state)
        assert score == 1.5  # simple task shortcut

    def test_simple_add_command_returns_low_score(self):
        score = self.analyzer.analyze_complexity("add a docstring to the function", self.state)
        assert score == 1.5

    def test_complex_task_returns_higher_score(self):
        msg = "create a new module and also add tests and configure CI/CD"
        score = self.analyzer.analyze_complexity(msg, self.state)
        assert score > 3.0

    def test_score_capped_at_10(self):
        # Very complex multi-step task with lots of conjunctions and action words
        msg = (
            "create build implement develop add update fix modify edit delete remove "
            "refactor test verify validate check deploy configure integrate and plus "
            "also additionally furthermore moreover in addition multiple several many "
            "various different all every entire whole complete full"
        )
        score = self.analyzer.analyze_complexity(msg, self.state)
        assert score == 10.0

    def test_score_minimum_above_1(self):
        score = self.analyzer.analyze_complexity("list the files", self.state)
        # "list" is a simple pattern match
        assert score == 1.5

    def test_action_word_adds_to_score(self):
        score = self.analyzer.analyze_complexity("create a new file", self.state)
        assert score > 1.5   # action word "create" adds score

    def test_file_mention_adds_small_score(self):
        score1 = self.analyzer.analyze_complexity("do something", self.state)
        score2 = self.analyzer.analyze_complexity("edit the .py file", self.state)
        assert score2 >= score1

    def test_none_state_does_not_crash(self):
        # state=None should not cause AttributeError
        score = self.analyzer.analyze_complexity("create a module", cast(State, None))
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# _is_simple_task
# ---------------------------------------------------------------------------

class TestIsSimpleTask:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())

    def test_question_is_simple(self):
        assert self.analyzer._is_simple_task("what is the function doing?") is True

    def test_how_question_is_simple(self):
        assert self.analyzer._is_simple_task("how does this work") is True

    def test_show_is_simple(self):
        assert self.analyzer._is_simple_task("show the list of items") is True

    def test_fix_typo_is_simple(self):
        assert self.analyzer._is_simple_task("fix a typo in module") is True

    def test_add_comment_is_simple(self):
        assert self.analyzer._is_simple_task("add a comment to the method") is True

    def test_complex_task_not_simple(self):
        assert self.analyzer._is_simple_task("build a full REST API with tests") is False


# ---------------------------------------------------------------------------
# _action_word_score
# ---------------------------------------------------------------------------

class TestActionWordScore:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())

    def test_no_action_words_returns_zero(self):
        assert self.analyzer._action_word_score("hello world") == 0.0

    def test_single_action_word(self):
        score = self.analyzer._action_word_score("create a module")
        assert score == 0.5

    def test_two_action_words(self):
        score = self.analyzer._action_word_score("create and build")
        assert score == 1.0

    def test_score_capped_at_3(self):
        # 7+ action words but cap is 3.0
        msg = "create build implement develop add update fix modify edit delete"
        score = self.analyzer._action_word_score(msg)
        assert score == 3.0

    def test_partial_word_not_matched(self):
        # "creates" should not match "create" as a whole word
        score = self.analyzer._action_word_score("creates some files")
        assert score == 0.0


# ---------------------------------------------------------------------------
# _complex_pattern_score
# ---------------------------------------------------------------------------

class TestComplexPatternScore:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())

    def test_no_patterns_returns_zero(self):
        assert self.analyzer._complex_pattern_score("do something simple") == 0.0

    def test_single_complex_pattern(self):
        # "refactor" matches exactly one COMPLEX_TASK_PATTERNS entry
        score = self.analyzer._complex_pattern_score("please refactor the module")
        assert score == pytest.approx(0.8)

    def test_multiple_patterns_accumulate(self):
        msg = "create and build multiple different things in addition to integration tests"
        score = self.analyzer._complex_pattern_score(msg)
        assert score > 0.8

    def test_score_capped_at_4(self):
        # Really complex description
        msg = (
            "and plus also additionally furthermore moreover in addition "
            "multiple several many various different all every entire whole complete full "
            "create and refactor integration multi-step"
        )
        score = self.analyzer._complex_pattern_score(msg)
        assert score == 4.0


# ---------------------------------------------------------------------------
# _conjunction_score
# ---------------------------------------------------------------------------

class TestConjunctionScore:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())

    def test_no_conjunctions_returns_zero(self):
        assert self.analyzer._conjunction_score("do something") == 0.0

    def test_single_and(self):
        score = self.analyzer._conjunction_score("create it and test it")
        assert score == pytest.approx(0.6)

    def test_multiple_conjunctions(self):
        score = self.analyzer._conjunction_score("create and build and test and deploy")
        assert score == pytest.approx(1.8)

    def test_score_capped_at_3(self):
        msg = " and " * 10  # 10 conjunctions
        score = self.analyzer._conjunction_score(msg)
        assert score == 3.0


# ---------------------------------------------------------------------------
# _file_mention_score
# ---------------------------------------------------------------------------

class TestFileMentionScore:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())

    def test_no_files_returns_zero(self):
        assert self.analyzer._file_mention_score("do something") == 0.0

    def test_single_file_extension(self):
        score = self.analyzer._file_mention_score("edit main.py")
        assert score == pytest.approx(0.3)

    def test_multiple_file_mentions(self):
        score = self.analyzer._file_mention_score("update the file and create files")
        assert score > 0.3

    def test_capped_at_2(self):
        msg = " file " * 20 + " files " * 20
        score = self.analyzer._file_mention_score(msg)
        assert score == 2.0


# ---------------------------------------------------------------------------
# _history_complexity_score
# ---------------------------------------------------------------------------

class TestHistoryComplexityScore:
    def setup_method(self):
        self.analyzer = TaskComplexityAnalyzer(_config())

    def test_none_state_returns_zero(self):
        assert self.analyzer._history_complexity_score(None) == 0.0

    def test_state_without_history_attr(self):
        state = MagicMock(spec=[])
        assert self.analyzer._history_complexity_score(state) == 0.0

    def test_empty_history_returns_zero(self):
        assert self.analyzer._history_complexity_score(_state([])) == 0.0

    def test_edit_actions_increase_score(self):
        state = _state()
        # Create mock events with action == "edit"
        event1 = MagicMock()
        event1.action = "edit"
        event2 = MagicMock()
        event2.action = "write"
        state.history = [event1, event2]
        score = self.analyzer._history_complexity_score(state)
        assert score > 0.0

    def test_non_edit_actions_no_increase(self):
        state = _state()
        event = MagicMock()
        event.action = "read"
        state.history = [event]
        score = self.analyzer._history_complexity_score(state)
        assert score == 0.0


# ---------------------------------------------------------------------------
# should_plan
# ---------------------------------------------------------------------------

class TestShouldPlan:
    def test_returns_false_when_auto_planning_disabled(self):
        cfg = _config(enable_auto_planning=False)
        analyzer = TaskComplexityAnalyzer(cfg)
        assert analyzer.should_plan("build and deploy a full app", _state()) is False

    def test_returns_true_when_complexity_above_threshold(self):
        cfg = _config(threshold=2.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        msg = "create a new module and add multiple tests and integrate with CI"
        assert analyzer.should_plan(msg, _state()) is True

    def test_returns_false_when_complexity_below_threshold(self):
        cfg = _config(threshold=5.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        assert analyzer.should_plan("what is this?", _state()) is False

    def test_simple_question_does_not_trigger_plan(self):
        cfg = _config(threshold=3.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        assert analyzer.should_plan("how does this work", _state()) is False


# ---------------------------------------------------------------------------
# estimate_iterations
# ---------------------------------------------------------------------------

class TestEstimateIterations:
    def test_dynamic_iterations_disabled_returns_override(self):
        cfg = _config(enable_dynamic_iterations=False, max_iterations_override=100)
        analyzer = TaskComplexityAnalyzer(cfg)
        result = analyzer.estimate_iterations(5.0, _state())
        assert result == 100

    def test_dynamic_iterations_disabled_no_override_returns_500(self):
        cfg = _config(enable_dynamic_iterations=False, max_iterations_override=None)
        analyzer = TaskComplexityAnalyzer(cfg)
        result = analyzer.estimate_iterations(5.0, _state())
        assert result == 500

    def test_low_complexity_returns_min_iterations(self):
        cfg = _config(min_iterations=20, max_iterations_override=500, complexity_iteration_multiplier=50.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        # 1.0 complexity: 20 + (1.0 * 50) = 70
        result = analyzer.estimate_iterations(1.0, _state())
        assert result == max(20, min(70, 500))

    def test_high_complexity_capped_at_max(self):
        cfg = _config(min_iterations=20, max_iterations_override=100, complexity_iteration_multiplier=50.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        # 10.0 complexity: 20 + (10.0 * 50) = 520, capped at 100
        result = analyzer.estimate_iterations(10.0, _state())
        assert result == 100

    def test_mid_complexity_uses_formula(self):
        cfg = _config(min_iterations=20, max_iterations_override=500, complexity_iteration_multiplier=50.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        # 4.0 complexity: int(20 + 4.0 * 50) = 220
        result = analyzer.estimate_iterations(4.0, _state())
        assert result == 220

    def test_min_iterations_respected_even_at_zero_complexity(self):
        cfg = _config(min_iterations=30, max_iterations_override=500, complexity_iteration_multiplier=50.0)
        analyzer = TaskComplexityAnalyzer(cfg)
        result = analyzer.estimate_iterations(0.0, _state())
        assert result >= 30
