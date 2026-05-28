"""Action scheduling policies for orchestrator batch execution.

This module centralizes concurrency decisions so parallel scheduling can be
extended incrementally without coupling policy logic to SessionOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.constants import DEFAULT_AGENT_PARALLEL_BATCH_SIZE
from backend.core.enums import ActionType

# ActionType values that are observation-only (no side effects) and safe to
# execute concurrently. Any batch containing an action outside this set
# degrades to sequential execution.
_PARALLEL_SAFE_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.READ,
    ActionType.LSP_QUERY,
    ActionType.THINK,
    ActionType.RECALL,
    ActionType.BROWSE_INTERACTIVE,
    ActionType.BROWSER_TOOL,
})

# MCP tool names that are read-only.  The generic MCP action cannot be
# classified by ActionType alone, so we check the tool name.
_PARALLEL_SAFE_MCP_TOOL_NAMES: frozenset[str] = frozenset({
    'search_code',
    'get_entity',
})

DEFAULT_MAX_PARALLEL_BATCH_SIZE = DEFAULT_AGENT_PARALLEL_BATCH_SIZE


@dataclass(frozen=True, slots=True)
class ParallelBatchDecision:
    """Result of evaluating whether a pending action list can run in parallel."""

    should_execute_parallel: bool
    actions: tuple[Any, ...]
    reason: str
    #: Actions that were safe for parallel execution but exceeded the batch
    #: size cap. The caller must re-queue these so they are not lost.
    overflow: tuple[Any, ...] = ()


class ActionScheduler:
    """Determines when queued actions are safe to execute concurrently.

    The policy is simple:
    - Observation-only actions (reads, queries, thinks) may run in parallel.
    - Any action with side effects forces the entire batch to sequential.
    - Mixed batches are *not* rejected --- they degrade to sequential so the
      agent's intent is always preserved.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        max_parallel_batch_size: int = DEFAULT_MAX_PARALLEL_BATCH_SIZE,
    ) -> None:
        self.enabled = enabled
        self.max_parallel_batch_size = max(1, max_parallel_batch_size)

    def is_parallel_safe(self, action: Any) -> bool:
        """Return True when an action is safe for concurrent execution."""
        action_type = str(getattr(action, 'action', '') or '')

        if action_type in _PARALLEL_SAFE_ACTION_TYPES:
            return True

        if action_type == ActionType.MCP:
            tool_name = str(getattr(action, 'name', '') or '')
            return tool_name in _PARALLEL_SAFE_MCP_TOOL_NAMES

        return False

    def decide_parallel_batch(self, actions: list[Any]) -> ParallelBatchDecision:
        """Return a conservative parallel-execution decision for pending actions.

        When the batch contains any action that isn't parallel-safe the
        decision returns ``should_execute_parallel=False`` so the caller
        falls through to sequential execution --- the agent's requested
        ordering is always preserved.
        """
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

        if any(not self.is_parallel_safe(a) for a in actions):
            return ParallelBatchDecision(
                should_execute_parallel=False,
                actions=(),
                reason='mixed_batch_sequential',
            )

        capped = tuple(actions[: self.max_parallel_batch_size])
        overflow = tuple(actions[self.max_parallel_batch_size :])
        reason = 'parallel_safe_batch' if not overflow else 'parallel_safe_batch_capped'
        return ParallelBatchDecision(
            should_execute_parallel=True,
            actions=capped,
            reason=reason,
            overflow=overflow,
        )
