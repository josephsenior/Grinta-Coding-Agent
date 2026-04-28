"""Action scheduling policies for orchestrator batch execution.

This module centralizes concurrency decisions so parallel scheduling can be
extended incrementally without coupling policy logic to SessionOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.constants import DEFAULT_AGENT_PARALLEL_BATCH_SIZE

DEFAULT_PARALLEL_SAFE_ACTION_PREFIXES: tuple[str, ...] = (
    'read',
    'think',
    'search_code',
    'explore_tree',
    'get_entity',
)
DEFAULT_MAX_PARALLEL_BATCH_SIZE = DEFAULT_AGENT_PARALLEL_BATCH_SIZE


@dataclass(frozen=True, slots=True)
class ParallelBatchDecision:
    """Result of evaluating whether a pending action list can run in parallel."""

    should_execute_parallel: bool
    actions: tuple[Any, ...]
    reason: str


class ActionScheduler:
    """Determines when queued actions are safe to execute concurrently."""

    def __init__(
        self,
        *,
        enabled: bool,
        parallel_safe_action_prefixes: tuple[
            str, ...
        ] = DEFAULT_PARALLEL_SAFE_ACTION_PREFIXES,
        max_parallel_batch_size: int = DEFAULT_MAX_PARALLEL_BATCH_SIZE,
    ) -> None:
        self.enabled = enabled
        self.parallel_safe_action_prefixes = parallel_safe_action_prefixes
        self.max_parallel_batch_size = max(1, max_parallel_batch_size)

    def is_parallel_safe(self, action: Any) -> bool:
        """Return True when an action is explicitly allowed for parallel execution."""
        action_type = str(getattr(action, 'action', '') or '')
        return any(
            action_type.startswith(prefix)
            for prefix in self.parallel_safe_action_prefixes
        )

    def decide_parallel_batch(self, actions: list[Any]) -> ParallelBatchDecision:
        """Return a conservative parallel-execution decision for pending actions."""
        if not self.enabled:
            return ParallelBatchDecision(
                should_execute_parallel=False,
                actions=(),
                reason='parallel_disabled',
            )

        if len(actions) < 2:
            return ParallelBatchDecision(
                should_execute_parallel=False,
                actions=(),
                reason='insufficient_actions',
            )

        if not all(self.is_parallel_safe(action) for action in actions):
            return ParallelBatchDecision(
                should_execute_parallel=False,
                actions=(),
                reason='contains_non_parallel_safe_action',
            )

        capped = tuple(actions[: self.max_parallel_batch_size])
        reason = (
            'parallel_safe_batch'
            if len(capped) == len(actions)
            else 'parallel_safe_batch_capped'
        )
        return ParallelBatchDecision(
            should_execute_parallel=True,
            actions=capped,
            reason=reason,
        )
