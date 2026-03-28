"""Unit tests for backend.orchestration.state.control_flags — iteration & budget limits."""

from __future__ import annotations

import pytest

from backend.orchestration.state.control_flags import (
    BudgetControlFlag,
    ControlFlag,
    IterationControlFlag,
)


# ---------------------------------------------------------------------------
# ControlFlag base (abstract)
# ---------------------------------------------------------------------------


class TestControlFlagBase:
    def test_reached_limit_not_implemented(self):
        flag = ControlFlag(limit_increase_amount=5, current_value=0, max_value=10)
        with pytest.raises(NotImplementedError):
            flag.reached_limit()

    def test_increase_limit_not_implemented(self):
        flag = ControlFlag(limit_increase_amount=5, current_value=0, max_value=10)
        with pytest.raises(NotImplementedError):
            flag.increase_limit(False)

    def test_step_not_implemented(self):
        flag = ControlFlag(limit_increase_amount=5, current_value=0, max_value=10)
        with pytest.raises(NotImplementedError):
            flag.step()


# ---------------------------------------------------------------------------
# IterationControlFlag
# ---------------------------------------------------------------------------


class TestIterationControlFlag:
    def test_initial_not_reached(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=0, max_value=10
        )
        assert flag.reached_limit() is False
        assert flag._hit_limit is False

    def test_reached_at_max(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=10, max_value=10
        )
        assert flag.reached_limit() is True
        assert flag._hit_limit is True

    def test_reached_above_max(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=15, max_value=10
        )
        assert flag.reached_limit() is True

    def test_step_increments(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=0, max_value=10
        )
        flag.step()
        assert flag.current_value == 1

    def test_step_raises_at_limit(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=10, max_value=10
        )
        with pytest.raises(RuntimeError, match="maximum iteration"):
            flag.step()

    def test_step_increments_up_to_limit(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=0, max_value=3
        )
        flag.step()  # 1
        flag.step()  # 2
        flag.step()  # 3: now current >= max
        with pytest.raises(RuntimeError):
            flag.step()
        assert flag.current_value == 3

    def test_increase_limit_interactive(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=10, max_value=10
        )
        flag.reached_limit()
        flag.increase_limit(headless_mode=False)
        assert flag.max_value == 15
        assert flag._hit_limit is False

    def test_increase_limit_headless_noop(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=10, max_value=10
        )
        flag.reached_limit()
        flag.increase_limit(headless_mode=True)
        assert flag.max_value == 10  # no change in headless

    def test_increase_limit_before_hitting_limit(self):
        flag = IterationControlFlag(
            limit_increase_amount=5, current_value=5, max_value=10
        )
        flag.reached_limit()  # _hit_limit = False
        flag.increase_limit(headless_mode=False)
        assert flag.max_value == 10  # unchanged since not hit

    def test_increase_allows_more_steps(self):
        flag = IterationControlFlag(
            limit_increase_amount=3, current_value=5, max_value=5
        )
        flag.reached_limit()
        flag.increase_limit(headless_mode=False)
        assert flag.max_value == 8
        flag.step()  # 6
        flag.step()  # 7
        flag.step()  # 8 = max again
        with pytest.raises(RuntimeError):
            flag.step()


# ---------------------------------------------------------------------------
# BudgetControlFlag
# ---------------------------------------------------------------------------


class TestBudgetControlFlag:
    def test_initial_not_reached(self):
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=0.0, max_value=10.0
        )
        assert flag.reached_limit() is False

    def test_reached_at_max(self):
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=10.0, max_value=10.0
        )
        assert flag.reached_limit() is True

    def test_reached_above_max(self):
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=12.0, max_value=10.0
        )
        assert flag.reached_limit() is True

    def test_step_raises_at_limit(self):
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=10.0, max_value=10.0
        )
        with pytest.raises(RuntimeError, match="maximum budget"):
            flag.step()

    def test_step_does_not_increment(self):
        """BudgetControlFlag.step() doesn't change current_value; it's updated externally."""
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=3.0, max_value=10.0
        )
        flag.step()
        assert flag.current_value == 3.0

    def test_increase_limit(self):
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=10.0, max_value=10.0
        )
        flag.reached_limit()
        flag.increase_limit(headless_mode=False)
        assert flag.max_value == 15.0  # current + increase_amount
        assert flag._hit_limit is False

    def test_increase_limit_headless_also_works(self):
        """BudgetControlFlag increases limit regardless of headless mode."""
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=10.0, max_value=10.0
        )
        flag.reached_limit()
        flag.increase_limit(headless_mode=True)
        assert flag.max_value == 15.0

    def test_increase_before_hit_noop(self):
        flag = BudgetControlFlag(
            limit_increase_amount=5.0, current_value=3.0, max_value=10.0
        )
        flag.reached_limit()
        flag.increase_limit(headless_mode=False)
        assert flag.max_value == 10.0  # not hit → no change

    def test_fractional_values(self):
        flag = BudgetControlFlag(
            limit_increase_amount=0.5, current_value=0.99, max_value=1.0
        )
        assert flag.reached_limit() is False
        flag.current_value = 1.0
        assert flag.reached_limit() is True
