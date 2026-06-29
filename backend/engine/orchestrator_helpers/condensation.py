"""Condensation event helpers extracted from :class:`Orchestrator`."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from backend.core.logging.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction
from backend.ledger.action.empty import NullAction, NullActionReason
from backend.ledger.event import EventSource

if TYPE_CHECKING:
    from backend.engine.orchestrator import Orchestrator
    from backend.ledger.action import Action
    from backend.orchestration.state.state import State


def _emit_compaction_status(orch: Orchestrator) -> None:
    """Emit a compaction status event so the TUI shows progress."""
    if orch.event_stream is None:
        return
    try:
        from backend.ledger.observation import StatusObservation

        status = StatusObservation(
            content='Compacting context...',
            status_type='compaction',
        )
        orch.event_stream.add_event(status, EventSource.AGENT)
    except Exception:
        logger.debug('Failed to emit compaction status', exc_info=True)


def _emit_compaction_status_if_needed(orch: Orchestrator, state: State) -> bool:
    """Emit compaction status before a foreground condensation blocks."""
    predictor = getattr(
        orch.memory_manager,
        'should_emit_compaction_status',
        None,
    )
    if not callable(predictor):
        return False
    try:
        should_emit = bool(predictor(state))
    except Exception:
        logger.debug('Failed to predict compaction status', exc_info=True)
        return False
    if not should_emit:
        return False
    _emit_compaction_status(orch)
    return True


def _set_skip_compaction_flag(state: State) -> None:
    """Mark pipeline state so ineffective compactions are skipped on the next turn."""
    from backend.context.context_pipeline import apply_ineffective_compaction_backoff

    apply_ineffective_compaction_backoff(state)
    pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
    count = pipe.get('consecutive_condensation_steps', 0)
    if not isinstance(count, int):
        count = 0
    pipe['consecutive_condensation_steps'] = count + 1
    state.set_extra('context_pipeline_state', pipe, source='OrchestratorCondensation')


def _queue_post_condensation_recovery(orch: Orchestrator, task_text: str = '') -> None:
    """Queue a silent no-op after condensation to break the re-condensation loop.

    The agent_controller drain loop calls astep() immediately after dispatching
    a CondensationAction. The event-delivery pipeline (background thread →
    ThreadPoolExecutor → call_soon_threadsafe → ensure_future) needs at least
    2 event-loop ticks before state.history reflects the CondensationAction.

    With only asyncio.sleep(0) (1 tick) in the drain loop, the next astep()
    call sees stale state, condense_history() concludes condensation is still
    needed, and returns another CondensationAction — an infinite loop.

    Queuing a sentinel NullAction here ensures _consume_pending_action() returns
    it on the very next astep() call, skipping condense_history() entirely.
    By the time the following step runs, state.history already contains the
    original CondensationAction. A NullAction is used instead of a think action
    so the TUI does not show a fake "Memory condensed" reasoning row — the
    compaction card already covers that UX.
    """
    del task_text  # Currently unused; reserved for future personalization.
    orch_state = getattr(orch, 'state', None)
    if orch_state is not None:
        _set_skip_compaction_flag(orch_state)
    orch.pending_actions.append(NullAction(reason=NullActionReason.SENTINEL))


def _is_noop_condensation_action(action: object | None) -> bool:
    if not isinstance(action, CondensationAction):
        return False
    return False if action.summary is not None else len(action.pruned) == 0


def _handle_pending_action_from_condensation(
    orch: Orchestrator, state: State, condensed: Any
) -> Action | None:
    """If condensed has pending_action, queue recovery and return it. Else None."""
    if not condensed.pending_action:
        return None
    if _is_noop_condensation_action(condensed.pending_action):
        return condensed.pending_action
    task_text = ''
    with contextlib.suppress(Exception):
        initial_msg = orch.memory_manager.get_initial_user_message(state.history)
        task_text = (getattr(initial_msg, 'content', '') or '')[:200]
    _queue_post_condensation_recovery(orch, task_text=task_text)
    return condensed.pending_action
