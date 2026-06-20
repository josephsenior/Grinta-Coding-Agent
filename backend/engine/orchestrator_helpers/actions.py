"""Action queue helpers extracted from :class:`Orchestrator`.

The functions in this module operate on the orchestrator's
``pending_actions`` and ``deferred_actions`` deques plus its executor
state. They take the orchestrator instance as the first argument so the
:class:`Orchestrator` class can stay as a thin coordinator.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from backend.core.interaction_modes import normalize_interaction_mode
from backend.core.logging.logger import app_logger as logger
from backend.ledger.observation.task_tracking import TaskTrackingObservation

if TYPE_CHECKING:
    from backend.orchestration.state.state import State
    from backend.engine.orchestrator import Orchestrator
    from backend.ledger.action import Action


def _consume_pending_action(orch: Orchestrator) -> Action | None:
    if not orch.pending_actions:
        return None
    from backend.engine.file_reads import try_batch_file_reads

    batched = try_batch_file_reads(orch.pending_actions)
    return batched if batched else orch.pending_actions.popleft()


def _queue_additional_actions(orch: Orchestrator, actions: list[Action]) -> None:
    for pending in actions:
        orch.pending_actions.append(pending)


def _promote_deferred_actions(orch: Orchestrator) -> None:
    """Promote a bounded set of deferred actions into the active queue."""
    while orch.deferred_actions:
        orch.pending_actions.append(orch.deferred_actions.popleft())


def _clear_queued_actions(orch: Orchestrator, reason: str = '') -> int:
    """Clear pending/deferred queues explicitly (used by stuck recovery)."""
    removed = len(orch.pending_actions) + len(orch.deferred_actions)
    orch.pending_actions.clear()
    orch.deferred_actions.clear()
    if removed > 0:
        logger.warning('Cleared %d queued actions (%s)', removed, reason or 'no reason')
    return removed


def _iter_queued_actions(orch: Orchestrator) -> Iterator[Action]:
    """Snapshot of all queued actions, pending first then deferred."""
    return iter([*orch.pending_actions, *orch.deferred_actions])


def _has_active_tasks_in_state(state: State) -> bool:
    """Check if state history contains any task in 'todo' or 'in_progress' status."""
    for event in getattr(state, 'history', []):
        if isinstance(event, TaskTrackingObservation):
            for task in getattr(event, 'task_list', []):
                status = (task.get('status') or '').lower()
                if status in ('todo', 'in_progress'):
                    return True
    return False


def _active_run_mode_for_state(orch: Orchestrator, state: State) -> str:
    extra = getattr(state, 'extra_data', {}) or {}
    if isinstance(extra, dict):
        active_mode = extra.get('active_run_mode')
        if active_mode:
            return normalize_interaction_mode(active_mode)
    return normalize_interaction_mode(getattr(orch.config, 'mode', 'agent'))


def _sync_executor_llm(orch: Orchestrator) -> None:
    if (
        hasattr(orch, 'executor')
        and getattr(orch.executor, '_llm', None) is not orch.llm
    ):
        with __import__('contextlib').suppress(Exception):
            orch.executor._llm = orch.llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
