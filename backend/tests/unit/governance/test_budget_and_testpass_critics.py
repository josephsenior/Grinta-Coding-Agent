"""Tests for BudgetCritic and SuitePassCritic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.governance.budget_critic import BudgetCritic, _extract_cost_from_events
from backend.governance.suite_pass_critic import (
    SuitePassCritic,
    _collect_test_dirs,
    _extract_touched_files,
)


# ── BudgetCritic ──────────────────────────────────────────────────────


class TestBudgetCritic:
    def _critic(self, max_budget: float = 10.0, actual_cost: float = 0.0) -> BudgetCritic:
        return BudgetCritic(max_budget=max_budget, actual_cost=actual_cost)

    def test_no_budget_configured(self):
        c = BudgetCritic()
        result = c.evaluate([])
        assert result.score == 1.0

    def test_well_within_budget(self):
        result = self._critic(max_budget=10.0, actual_cost=4.0).evaluate([])
        assert result.score == 1.0

    def test_acceptable_usage(self):
        result = self._critic(max_budget=10.0, actual_cost=7.0).evaluate([])
        assert result.score == 0.8

    def test_tight_but_within_budget(self):
        result = self._critic(max_budget=10.0, actual_cost=9.0).evaluate([])
        assert result.score == 0.5

    def test_over_budget(self):
        result = self._critic(max_budget=10.0, actual_cost=11.0).evaluate([])
        assert result.score == 0.0

    def test_exactly_at_50_pct(self):
        result = self._critic(max_budget=10.0, actual_cost=5.0).evaluate([])
        assert result.score == 1.0

    def test_exactly_at_80_pct(self):
        result = self._critic(max_budget=10.0, actual_cost=8.0).evaluate([])
        assert result.score == 0.8

    def test_exactly_at_100_pct(self):
        result = self._critic(max_budget=10.0, actual_cost=10.0).evaluate([])
        assert result.score == 0.5

    def test_message_shows_dollar_amounts(self):
        result = self._critic(max_budget=5.00, actual_cost=4.80).evaluate([])


    def test_zero_cost_full_budget(self):
        result = self._critic(max_budget=10.0, actual_cost=0.0).evaluate([])
        assert result.score == 1.0

    def test_extract_cost_from_events_no_metrics(self):
        events = [MagicMock(spec=object)]
        cost, budget = _extract_cost_from_events(events)
        assert cost == 0.0
        assert budget == 0.0

    def test_extract_cost_from_events_with_metrics(self):
        metrics = MagicMock()
        metrics.accumulated_cost = 3.14
        metrics.max_budget_per_task = 10.0
        event = MagicMock()
        event.metrics = metrics
        cost, budget = _extract_cost_from_events([event])
        assert cost == pytest.approx(3.14)
        assert budget == pytest.approx(10.0)

    def test_evaluate_reads_from_events_when_no_constructor_budget(self):
        metrics = MagicMock()
        metrics.accumulated_cost = 1.0
        metrics.max_budget_per_task = 10.0
        event = MagicMock()
        event.metrics = metrics
        result = BudgetCritic().evaluate([event])
        assert result.score == 1.0  # 10% usage → well within budget


# ── SuitePassCritic ────────────────────────────────────────────────────


class TestSuitePassCritic:
    def test_no_events_gives_perfect_score(self):
        critic = SuitePassCritic()
        result = critic.evaluate([])
        assert result.score == 1.0

    def test_no_touched_files_gives_perfect_score(self):
        # Events with no .path attribute
        events = [MagicMock(spec=object)]
        critic = SuitePassCritic()
        result = critic.evaluate(events)
        assert result.score == 1.0

    def test_extract_touched_files_from_path_attr(self):
        e1 = MagicMock()
        e1.path = "src/foo.py"
        e2 = MagicMock()
        e2.path = "src/bar.py"
        e3 = MagicMock()
        del e3.path  # no .path
        touched = _extract_touched_files([e1, e2, e3])
        assert "src/foo.py" in touched
        assert "src/bar.py" in touched
        assert len(touched) == 2

    def test_extract_touched_files_deduplicates(self):
        e1, e2 = MagicMock(), MagicMock()
        e1.path = "src/foo.py"
        e2.path = "src/foo.py"
        assert len(_extract_touched_files([e1, e2])) == 1

    def test_collect_test_dirs_finds_test_file(self, tmp_path):
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_foo.py"
        test_file.write_text("")
        dirs = _collect_test_dirs(["tests/test_foo.py"], str(tmp_path))
        assert any("tests" in str(d) for d in dirs)

    def test_collect_test_dirs_fallback_to_adjacent_tests_dir(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "foo.py").write_text("")
        tests_dir = src_dir / "tests"
        tests_dir.mkdir()
        dirs = _collect_test_dirs(["src/foo.py"], str(tmp_path))
        assert tests_dir in dirs

    def test_all_tests_pass(self, tmp_path):
        critic = SuitePassCritic(workspace_root=str(tmp_path))
        with patch("backend.governance.suite_pass_critic._run_pytest", return_value=(5, 0, "5 passed")):
            with patch("backend.governance.suite_pass_critic._collect_test_dirs", return_value=[tmp_path]):
                e = MagicMock()
                e.path = "src/foo.py"
                result = critic.evaluate([e])
        assert result.score == 1.0

    def test_some_tests_fail(self, tmp_path):
        critic = SuitePassCritic(workspace_root=str(tmp_path))
        with patch("backend.governance.suite_pass_critic._run_pytest", return_value=(3, 2, "3 passed, 2 failed")):
            with patch("backend.governance.suite_pass_critic._collect_test_dirs", return_value=[tmp_path]):
                e = MagicMock()
                e.path = "src/foo.py"
                result = critic.evaluate([e])
        assert result.score == pytest.approx(0.6)

    def test_all_tests_fail(self, tmp_path):
        critic = SuitePassCritic(workspace_root=str(tmp_path))
        with patch("backend.governance.suite_pass_critic._run_pytest", return_value=(0, 4, "4 failed")):
            with patch("backend.governance.suite_pass_critic._collect_test_dirs", return_value=[tmp_path]):
                e = MagicMock()
                e.path = "src/foo.py"
                result = critic.evaluate([e])
        assert result.score == 0.0

    def test_pytest_returns_zero_results(self, tmp_path):
        critic = SuitePassCritic(workspace_root=str(tmp_path))
        with patch("backend.governance.suite_pass_critic._run_pytest", return_value=(0, 0, "")):
            with patch("backend.governance.suite_pass_critic._collect_test_dirs", return_value=[tmp_path]):
                e = MagicMock()
                e.path = "src/foo.py"
                result = critic.evaluate([e])
        # 0 total — treated as no results found
        assert result.score == 1.0
