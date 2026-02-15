"""Control flag classes for enforcing iteration and budget limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T", int, float)


@dataclass
class ControlFlag(Generic[T]):
    """Base class for control flags that manage limits and state transitions."""

    limit_increase_amount: T
    current_value: T
    max_value: T
    headless_mode: bool = False
    _hit_limit: bool = False

    def reached_limit(self) -> bool:
        """Check if the limit has been reached.

        Returns:
            bool: True if the limit has been reached, False otherwise.

        """
        raise NotImplementedError

    def increase_limit(self, headless_mode: bool) -> None:
        """Expand the limit when needed."""
        raise NotImplementedError

    def step(self) -> None:
        """Determine the next state based on the current state and mode.

        Returns:
            ControlFlagState: The next state.

        """
        raise NotImplementedError


@dataclass
class IterationControlFlag(ControlFlag[int]):
    """Control flag for managing iteration limits."""

    def reached_limit(self) -> bool:
        """Check if the iteration limit has been reached."""
        self._hit_limit = self.current_value >= self.max_value
        return self._hit_limit

    def increase_limit(self, headless_mode: bool) -> None:
        """Expand the iteration limit by adding the initial value."""
        if not headless_mode and self._hit_limit:
            self.max_value += self.limit_increase_amount
            self._hit_limit = False

    def step(self) -> None:
        """Increment iteration counter.

        Raises:
            RuntimeError: If iteration limit reached

        """
        if self.reached_limit():
            msg = f"Agent reached maximum iteration. Current iteration: {
                self.current_value
            }, max iteration: {self.max_value}"
            raise RuntimeError(
                msg,
            )
        self.current_value += 1


@dataclass
class BudgetControlFlag(ControlFlag[float]):
    """Control flag for managing budget limits."""

    def reached_limit(self) -> bool:
        """Check if the budget limit has been reached."""
        self._hit_limit = self.current_value >= self.max_value
        return self._hit_limit

    def increase_limit(self, headless_mode: bool) -> None:
        """Expand the budget limit by adding the initial value to the current value."""
        if self._hit_limit:
            self.max_value = self.current_value + self.limit_increase_amount
            self._hit_limit = False

    def step(self) -> None:
        """Check if we've reached the limit and update state accordingly.

        Note: Unlike IterationControlFlag, this doesn't increment the value
        as the budget is updated externally.
        """
        if self.reached_limit():
            current_str = f"{self.current_value:.2f}"
            max_str = f"{self.max_value:.2f}"
            msg = f"Agent reached maximum budget for conversation.Current budget: {current_str}, max budget: {max_str}"
            raise RuntimeError(
                msg,
            )
