"""Control flag classes for enforcing iteration and budget limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from backend.core.errors import AgentLimitExceededError

T = TypeVar('T', int, float)


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
        hit = self.current_value >= self.max_value
        self._hit_limit = hit
        return hit

    def increase_limit(self, headless_mode: bool) -> None:
        """Expand the iteration limit by adding the initial value."""
        if not headless_mode and self._hit_limit:
            self.max_value += self.limit_increase_amount
            self._hit_limit = False

    def step(self) -> None:
        """Increment iteration counter.

        Raises:
            AgentLimitExceededError: If iteration limit reached
        """
        if self.reached_limit():
            msg = (
                f'Agent reached maximum iteration. Current iteration: '
                f'{self.current_value}, max iteration: {self.max_value}'
            )
            raise AgentLimitExceededError(msg)
        self.current_value += 1


@dataclass
class BudgetControlFlag(ControlFlag[float]):
    """Control flag for managing budget limits."""

    def reached_limit(self) -> bool:
        """Check if the budget limit has been reached."""
        hit = self.current_value >= self.max_value
        self._hit_limit = hit
        return hit

    def increase_limit(self, headless_mode: bool) -> None:
        """Expand the budget limit by adding the increase amount to the max value.

        Unlike :class:`IterationControlFlag`, budget increases are applied
        regardless of ``headless_mode`` — the budget should grow whenever
        the limit is hit, ensuring the agent has room to complete its task.

        The new max is ``previous_max + limit_increase_amount``, which mirrors
        :class:`IterationControlFlag` semantics and ensures the budget actually
        grows when increased.
        """
        if self._hit_limit:
            self.max_value += self.limit_increase_amount
            self._hit_limit = False

    def step(self) -> None:
        """Check if we've reached the limit and update state accordingly.

        Note: Unlike IterationControlFlag, this doesn't increment the value
        as the budget is updated externally.

        Raises:
            AgentLimitExceededError: If budget limit reached
        """
        if self.reached_limit():
            current_str = f'{self.current_value:.2f}'
            max_str = f'{self.max_value:.2f}'
            msg = (
                f'Agent reached maximum budget for conversation. '
                f'Current budget: {current_str}, max budget: {max_str}'
            )
            raise AgentLimitExceededError(msg)
