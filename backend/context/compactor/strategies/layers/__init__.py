"""Composable compaction pipeline layers.

Each layer is an async function with signature:

    async def layer(events: list[Event], state: State | None = None) -> list[Event]:

Layers are applied in order by CompositionCompactor. Each layer
transforms the event list and passes it to the next.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from backend.context.compactor.strategies.microcompact_compactor import (
    _clear_observation_content,
    _is_microcompactable,
    _should_preserve_observation,
)
from backend.ledger.observation import Observation
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileReadObservation

if TYPE_CHECKING:
    from backend.context.compactor.compactor import Compactor
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State

LayerFn = Callable[..., Awaitable[list[Any]]]


MICROCOMPACT_RECENCY_WINDOW = 50
SNIP_MAX_EVENTS = 1000
SUMMARY_RECENCY_WINDOW = 50
POST_COMPACT_BUDGET = 50000
POST_COMPACT_MAX_FILES = 5
POST_COMPACT_MAX_TOKENS_PER_FILE = 5000
REACTIVE_COMPACT_RATIO = 0.5


async def microcompact_layer(
    events: list[Event],
    state: State | None = None,
    *,
    recency_window: int = MICROCOMPACT_RECENCY_WINDOW,
) -> list[Event]:
    """Clear old tool observation content bodies outside recency window.

    Preserves event count and structure so causal chains and compaction
    boundaries remain stable. Keeps observations with important keywords
    (error, failed, traceback, etc.) intact.
    """
    cutoff = max(0, len(events) - recency_window)
    results: list[Event] = []
    cleared = 0
    for index, event in enumerate(events):
        if index < cutoff and _is_microcompactable(event):
            if isinstance(event, AgentCondensationObservation):
                results.append(event)
                continue
            if _should_preserve_observation(event):
                results.append(event)
                continue
            results.append(_clear_observation_content(event))
            cleared += 1
            continue
        if index < cutoff and isinstance(event, Observation):
            if isinstance(event, (ErrorObservation, AgentCondensationObservation)):
                results.append(event)
                continue
        results.append(event)
    return results


async def snip_layer(
    events: list[Event],
    state: State | None = None,
    *,
    max_events: int = SNIP_MAX_EVENTS,
) -> list[Event]:
    """Hard cap on total event count. Drops oldest events past max_events."""
    if len(events) > max_events:
        return events[-max_events:]
    return events


async def summary_layer(
    events: list[Event],
    state: State | None = None,
    summary_compactor: Compactor | None = None,
    summary_recency: int = SUMMARY_RECENCY_WINDOW,
) -> list[Event]:
    """Summarize old events before the recency window using an LLM compactor.

    Splits events at the recency boundary. Old events are passed to the
    ``summary_compactor`` (a StructuredSummaryCompactor instance) which
    generates a single prose summary. Recent events stay raw.

    Args:
        events: Full event list.
        state: Optional orchestration state for layer-specific metadata.
        summary_compactor: LLM-based compactor from StructuredSummaryCompactor.
        summary_recency: Number of recent events to keep raw.

    Returns:
        Events with old portion replaced by a summary observation, or
        unchanged if no compactor is available or old events are empty.
    """
    if summary_compactor is None:
        return events

    if len(events) <= summary_recency:
        return events

    old_events = events[:-summary_recency]
    recent_events = events[-summary_recency:]

    from backend.context.view import View

    old_view = View(events=old_events)
    result = await summary_compactor.compact(old_view)

    from backend.context.compactor.compactor import Compaction

    if isinstance(result, Compaction):
        if getattr(summary_compactor, 'last_degraded', False):
            return events
        summary_text = result.action.summary
        if summary_text:
            summary_obs = AgentCondensationObservation(content=summary_text)
            return [summary_obs] + recent_events

    return events


async def recent_keep_layer(
    events: list[Event],
    state: State | None = None,
) -> list[Event]:
    """Ensure the last N events are always present in the result."""
    return events


async def post_compact_reattach_layer(
    events: list[Event],
    state: State | None = None,
) -> list[Event]:
    """Re-attach file read events for files that were modified in the session.

    Scans events for file edits, then injects FileReadObservation events
    for the N most-recently modified files. Respects POST_COMPACT_BUDGET.
    """
    seen_paths: set[str] = set()
    changed_files: list[str] = []
    for event in reversed(events):
        fpath = getattr(event, 'file_path', None) or getattr(event, 'path', None)
        if isinstance(fpath, str) and fpath not in seen_paths:
            seen_paths.add(fpath)
            changed_files.append(fpath)
        if len(changed_files) >= POST_COMPACT_MAX_FILES:
            break

    if not changed_files:
        return events

    inserted: list[Event] = []
    budget_remaining = POST_COMPACT_BUDGET
    for fpath in changed_files:
        if budget_remaining <= 0:
            break
        estimate = len(fpath) * 4
        if estimate > POST_COMPACT_MAX_TOKENS_PER_FILE:
            continue
        budget_remaining -= estimate
        try:
            obs = FileReadObservation(
                path=fpath,
                content=f'[re-attached by post-compact: {fpath}]',
            )
            inserted.append(obs)
        except Exception:
            pass

    if inserted:
        return inserted + events
    return events


async def reactive_compact_layer(
    events: list[Event],
    state: State | None = None,
    *,
    max_events: int = int(SNIP_MAX_EVENTS * REACTIVE_COMPACT_RATIO),
) -> list[Event]:
    """Safety net: peel oldest events when count still exceeds *max_events*.

    Runs after snip/summary/reattach, so *max_events* should be lower than the
    snip hard cap (default: half of ``SNIP_MAX_EVENTS``).
    """
    if len(events) > max_events:
        drop_count = max(1, int(len(events) * REACTIVE_COMPACT_RATIO))
        return events[drop_count:]
    return events


LAYERS: list[tuple[str, LayerFn]] = [
    ('microcompact', microcompact_layer),
    ('snip', snip_layer),
    ('summary', summary_layer),
    ('recent_keep', recent_keep_layer),
    ('post_compact_reattach', post_compact_reattach_layer),
    ('reactive', reactive_compact_layer),
]
