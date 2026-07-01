"""Action scheduling policies for orchestrator batch execution.

This module centralises concurrency decisions so parallel scheduling can be
extended incrementally without coupling policy logic to SessionOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.constants import DEFAULT_AGENT_PARALLEL_BATCH_SIZE
from backend.core.enums import ActionType

# Action types that are observation-only (no side effects) and safe to
# execute concurrently in any mix (read + lsp + think + etc.).
_READ_ONLY_ACTION_TYPES: frozenset[str] = frozenset(
    {
        ActionType.READ,
        ActionType.LSP_QUERY,
        ActionType.THINK,
        ActionType.RECALL,
        ActionType.BROWSE_INTERACTIVE,
        ActionType.BROWSER_TOOL,
    }
)

# MCP tool names that are read-only.
_READ_ONLY_MCP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        'grep',
        'glob',
        'get_entity',
    }
)

# Side-effect action types that may run in parallel when every action in the
# batch shares the same category **and** targets a different resource (file
# path, terminal session, etc.).  Each entry maps an ActionType string to a
# logical category key.
_SAME_TYPE_CATEGORIES: dict[str, str] = {
    ActionType.TERMINAL_RUN: 'terminal',
    ActionType.TERMINAL_INPUT: 'terminal',
    ActionType.TERMINAL_READ: 'terminal',
    ActionType.TERMINAL_CLOSE: 'terminal',
    ActionType.EDIT: 'file_edit',
}

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

    Policy summary (``enabled=True``):

    * Read-only actions (reads, queries, thinks) may run in parallel in any
      mix — they have no side effects.
    * Same-type write-side-effect actions (e.g. multiple ``terminal_run``,
      all ``edit`` to different files, all ``write`` to different files) may
      also run in parallel **when they target distinct resources**.
    * Actions that target the same resource (same file path, same terminal
      session) always run sequentially.
    * Mixed-type batches (e.g. a read + a write, a terminal + an edit) always
      degrade to sequential so the agent's intent is preserved.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        max_parallel_batch_size: int = DEFAULT_MAX_PARALLEL_BATCH_SIZE,
    ) -> None:
        self.enabled = enabled
        self.max_parallel_batch_size = max(1, max_parallel_batch_size)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _action_type(action: Any) -> str:
        return str(getattr(action, 'action', '') or '')

    @staticmethod
    def _resource_key(action: Any) -> str | None:
        """Return a resource identifier for conflict detection.

        Actions in the same same-type category with the same resource key
        cannot execute concurrently (e.g. two edits to the same file, two
        ``terminal_read`` on the same session).
        """
        path: Any = getattr(action, 'path', None)
        if path:
            return str(path)
        session_id: Any = getattr(action, 'session_id', None)
        if session_id is not None:
            return str(session_id)
        return None

    def _classify(self, action: Any) -> str | None:
        """Classify *action* into a concurrency category.

        Returns:
        -------
        ``'read_only'``
            Always parallel-safe with any other ``'read_only'`` action.
        A same-type category key (e.g. ``'terminal'``, ``'file_write'``)
            Parallel-safe when **every** action in the batch shares this key
            and all ``_resource_key()`` values differ.
        ``None``
            This action cannot run in parallel with any other action.
        """
        action_type = self._action_type(action)

        if action_type in _READ_ONLY_ACTION_TYPES:
            return 'read_only'

        if action_type == ActionType.MCP:
            tool_name = str(getattr(action, 'name', '') or '')
            if tool_name in _READ_ONLY_MCP_TOOL_NAMES:
                return 'read_only'
            return None  # Opaque MCP tools are always sequential

        return _SAME_TYPE_CATEGORIES.get(action_type)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide_parallel_batch(self, actions: list[Any]) -> ParallelBatchDecision:
        if not self.enabled:
            return ParallelBatchDecision(
                should_execute_parallel=False, actions=(), reason='parallel_disabled'
            )
        if len(actions) < 2:
            return ParallelBatchDecision(
                should_execute_parallel=False, actions=(), reason='insufficient_actions'
            )

        classified = [(self._classify(a), self._resource_key(a)) for a in actions]
        categories = {c for c, _ in classified}

        if None in categories:
            return ParallelBatchDecision(
                should_execute_parallel=False,
                actions=(),
                reason='mixed_batch_sequential',
            )
        if categories == {'read_only'}:
            return self._make_parallel_decision(actions)
        if len(categories) == 1:
            if self._no_resource_conflicts(classified):
                return self._make_parallel_decision(actions)
            return ParallelBatchDecision(
                should_execute_parallel=False,
                actions=(),
                reason='same_resource_conflict',
            )

        return ParallelBatchDecision(
            should_execute_parallel=False, actions=(), reason='mixed_batch_sequential'
        )

    def _make_parallel_decision(self, actions: list[Any]) -> ParallelBatchDecision:
        capped = tuple(actions[: self.max_parallel_batch_size])
        overflow = tuple(actions[self.max_parallel_batch_size :])
        reason = 'parallel_safe_batch' if not overflow else 'parallel_safe_batch_capped'
        return ParallelBatchDecision(
            should_execute_parallel=True,
            actions=capped,
            reason=reason,
            overflow=overflow,
        )

    def _no_resource_conflicts(
        self, classified: list[tuple[str | None, str | None]]
    ) -> bool:
        seen: set[str] = set()
        for _, rk in classified:
            if rk is not None and rk in seen:
                return False
            if rk is not None:
                seen.add(rk)
        return True
