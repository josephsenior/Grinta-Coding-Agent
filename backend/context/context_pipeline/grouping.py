"""API-round-style event grouping for compaction retries and reactive recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.ledger.event import Event


def group_events_by_api_round(events: list[Event]) -> list[list[Event]]:
    """Group events at action→observation causal boundaries.

    Each chunk starts with an :class:`Action` (tool call, message, etc.) and
    includes following observations until the next action. This approximates
    Claude Code's API-round grouping for agentic single-turn workloads.
    """
    from backend.ledger.action import Action

    groups: list[list[Event]] = []
    current: list[Event] = []
    for event in events:
        if isinstance(event, Action) and current:
            groups.append(current)
            current = [event]
        else:
            current.append(event)
    if current:
        groups.append(current)
    return groups


def peel_oldest_api_round_groups(
    events: list[Event],
    *,
    groups_to_peel: int = 1,
) -> list[Event] | None:
    """Drop the oldest API-round groups; return flattened events or None if empty."""
    if groups_to_peel < 1 or not events:
        return None
    groups = group_events_by_api_round(events)
    if len(groups) <= groups_to_peel:
        return None
    peeled = [event for group in groups[groups_to_peel:] for event in group]
    return peeled if peeled else None


def adjust_tail_for_api_invariants(
    tail: list[Event],
    all_events: list[Event],
    *,
    min_tool_loops: int = 2,
) -> list[Event]:
    """Ensure tool action/observation pairing in the preserved tail."""
    from backend.context.prompt.prompt_window import (
        _enforce_min_tool_loops,
        _protected_summary_events,
    )

    protected = _protected_summary_events(all_events)
    return _enforce_min_tool_loops(
        tail,
        all_events,
        protected,
        min_tool_loops=min_tool_loops,
    )


__all__ = [
    'adjust_tail_for_api_invariants',
    'group_events_by_api_round',
    'peel_oldest_api_round_groups',
]
