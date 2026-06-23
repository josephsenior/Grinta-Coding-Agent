"""Split submodule — see package facade for public API."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from backend.context.compactor.compact_boundary import project_after_compact_boundary
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline.types import (
    _COMPACTION_TARGET_RATIO,
    _INEFFECTIVE_COMPACT_STREAK_KEY,
    _INEFFECTIVE_COMPACT_UNTIL_KEY,
    _SKIP_COMPACTION_UNTIL_KEY,
)
from backend.context.prompt.context_packet import (
    CONTEXT_PACKET_MARKER,
)
from backend.core.constants import (
    DEFAULT_COMPACT_MIN_PRUNED_EVENTS,
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
    DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS,
    DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS,
    DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    DEFAULT_PROMPT_MIN_TOOL_LOOPS,
)
from backend.core.logging.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


def _latest_event_id(events: list[Event]) -> int | None:
    ids = [getattr(event, 'id', None) for event in events]
    int_ids = [event_id for event_id in ids if isinstance(event_id, int)]
    return max(int_ids) if int_ids else None


def _drop_stale_prompt_state_artifacts(events: list[Event]) -> list[Event]:
    """Remove old prompt-only state blocks before injecting the fresh packet."""
    markers = (
        CONTEXT_PACKET_MARKER,
        '<POST_COMPACT_RESTORE>',
        '<RESTORED_CONTEXT>',
    )
    filtered: list[Event] = []
    for event in events:
        content = getattr(event, 'content', None)
        if isinstance(content, str) and any(marker in content for marker in markers):
            continue
        filtered.append(event)
    return filtered


def apply_ineffective_compaction_backoff(state: State) -> None:
    """Backoff compaction after an ineffective prune (shared with orchestrator)."""
    pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
    history = list(getattr(state, 'history', []))
    latest_id = getattr(history[-1], 'id', None) if history else None
    if not isinstance(latest_id, int):
        return
    streak = pipe.get(_INEFFECTIVE_COMPACT_STREAK_KEY, 0)
    if not isinstance(streak, int):
        streak = 0
    streak += 1
    skip_events = min(
        DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS * streak,
        DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS,
    )
    pipe[_SKIP_COMPACTION_UNTIL_KEY] = latest_id + skip_events
    pipe[_INEFFECTIVE_COMPACT_STREAK_KEY] = streak
    pipe[_INEFFECTIVE_COMPACT_UNTIL_KEY] = (
        time.time() + DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS * min(streak, 4)
    )
    state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
    logger.info(
        'Compaction backoff: skip until event id>=%d (%d new events) for %.0fs (streak=%d)',
        pipe[_SKIP_COMPACTION_UNTIL_KEY],
        skip_events,
        pipe[_INEFFECTIVE_COMPACT_UNTIL_KEY] - time.time(),
        streak,
    )


def _projected_compaction_token_reduction(
    events: list[Event],
    tail: list[Event],
    *,
    history: list[Event],
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
    summary: str,
) -> int:
    pruned = _pruned_ids(events, tail)
    if len(pruned) < DEFAULT_COMPACT_MIN_PRUNED_EVENTS:
        return 0
    action = CondensationAction(
        pruned_event_ids=sorted(pruned),
        summary=summary or 'summary',
        summary_offset=0,
    )
    post_events = project_after_compact_boundary(
        _synthetic_history_after_action(history, action)
    )
    post_budget = ContextBudget.from_events(
        post_events, llm_config=llm_config, state=state
    )
    return budget.estimated_tokens - post_budget.estimated_tokens


def _shrink_tail_for_token_reduction(
    events: list[Event],
    tail: list[Event],
    *,
    history: list[Event],
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
    summary: str,
    min_reduction: int = DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
) -> list[Event]:
    """Drop oldest non-protected tail events until projected token savings meet the gate."""
    from backend.context.prompt.prompt_window import _protected_summary_events

    protected = _protected_summary_events(events)
    protected_ids = {id(event) for event in protected}
    current = list(tail)
    summary_text = summary.strip() or 'summary'

    while len(current) > len(protected):
        reduction = _projected_compaction_token_reduction(
            events,
            current,
            history=history,
            budget=budget,
            state=state,
            llm_config=llm_config,
            summary=summary_text,
        )
        if reduction >= min_reduction:
            break
        removed = False
        for index, event in enumerate(current):
            if id(event) in protected_ids:
                continue
            current.pop(index)
            removed = True
            break
        if not removed:
            break
    return current


def _select_compaction_tail(
    events: list[Event],
    budget: ContextBudget,
    *,
    llm_config: object | None,
    tail_ratio: float = _COMPACTION_TARGET_RATIO,
) -> list[Event]:
    from backend.context.prompt.prompt_window import (
        _enforce_min_tool_loops,
        _protected_summary_events,
        estimate_prompt_events_tokens,
    )

    protected = _protected_summary_events(events)
    protected_ids = {id(event) for event in protected}
    target_tokens = int(budget.autocompact_threshold * tail_ratio)
    min_tail_floor = min(DEFAULT_PROMPT_MIN_TAIL_TOKENS, target_tokens)
    tail: list[Event] = list(protected)
    tail_ids = set(protected_ids)
    tail_tokens = estimate_prompt_events_tokens(tail)

    for event in reversed(events):
        if id(event) in tail_ids:
            continue
        event_tokens = estimate_prompt_events_tokens([event])
        if tail_tokens + event_tokens > target_tokens and tail_tokens >= min_tail_floor:
            break
        tail.insert(0, event)
        tail_ids.add(id(event))
        tail_tokens += event_tokens
        if tail_tokens >= target_tokens:
            break

    tail = _enforce_min_tool_loops(
        tail,
        events,
        protected,
        min_tool_loops=DEFAULT_PROMPT_MIN_TOOL_LOOPS,
    )
    if estimate_prompt_events_tokens(tail) < min_tail_floor:
        kept_ids = {id(item) for item in tail}
        for event in reversed(events):
            if id(event) in kept_ids:
                continue
            tail.insert(0, event)
            kept_ids.add(id(event))
            if estimate_prompt_events_tokens(tail) >= min_tail_floor:
                break
    del llm_config
    return tail


def _pruned_ids(events: list[Event], tail: list[Event]) -> set[int]:
    tail_ids = {
        event_id
        for event in tail
        if isinstance((event_id := getattr(event, 'id', None)), int)
    }
    pruned: set[int] = set()
    for event in events:
        event_id = getattr(event, 'id', None)
        if isinstance(event_id, int) and event_id not in tail_ids:
            pruned.add(event_id)
    return pruned


def _synthetic_history_after_action(
    history: list[Event], action: CondensationAction
) -> list[Event]:
    return [*history, action]


__all__ = [
    'apply_ineffective_compaction_backoff',
]
