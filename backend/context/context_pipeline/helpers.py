"""Context pipeline state helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from backend.context.context_pipeline.types import (
    _JUST_COMPACTED_KEY,
    _LAST_LLM_STEP_KEY,
)
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event
from backend.ledger.observation.agent import AgentCondensationObservation

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


def _drop_stale_prompt_state_artifacts(events: list[Event]) -> list[Event]:
    """Remove superseded prompt packets by event type, never content matching."""
    return [
        event
        for event in events
        if not (
            isinstance(event, AgentCondensationObservation)
            and getattr(event, 'is_working_set', False)
        )
    ]


def clear_compact_guard_after_llm_step(state: State) -> None:
    """Clear same-turn compaction guard after a real LLM step completes."""
    pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
    pipe[_LAST_LLM_STEP_KEY] = time.time()
    pipe[_JUST_COMPACTED_KEY] = False
    state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')


def is_prewarm_stale(history: list[Event], turn_signals: object | None) -> bool:
    """Return True when background prewarm was computed on a different history snapshot."""
    if turn_signals is None:
        return False
    prewarm_len = getattr(turn_signals, 'prewarm_history_len', None)
    if not isinstance(prewarm_len, int):
        return False
    prewarm_latest_id = getattr(turn_signals, 'prewarm_latest_event_id', None)
    current_len = len(history)
    current_latest_id = getattr(history[-1], 'id', None) if history else None
    return prewarm_len != current_len or prewarm_latest_id != current_latest_id


def clear_prewarm_signals(turn_signals: object | None) -> None:
    """Clear prewarm metadata after consumption or discard."""
    if turn_signals is None:
        return
    if hasattr(turn_signals, 'prewarmed_compaction'):
        turn_signals.prewarmed_compaction = None
    if hasattr(turn_signals, 'prewarm_history_len'):
        turn_signals.prewarm_history_len = None
    if hasattr(turn_signals, 'prewarm_latest_event_id'):
        turn_signals.prewarm_latest_event_id = None


def _synthetic_history_after_action(
    history: list[Event], action: CondensationAction
) -> list[Event]:
    return [*history, action]
