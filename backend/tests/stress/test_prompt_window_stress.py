"""Stress tests for prompt windowing on large histories."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.context.prompt.prompt_window import select_prompt_events
from backend.ledger.action import CmdRunAction, MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation import CmdOutputObservation
from backend.ledger.observation.agent import AgentCondensationObservation

pytestmark = pytest.mark.stress


def _build_large_history(event_count: int = 800) -> list:
    events: list = []
    start = MessageAction(content='stress session start')
    start.source = EventSource.USER
    start.id = 0
    events.append(start)

    summary = AgentCondensationObservation(content='condensed older context')
    summary.id = 1
    events.append(summary)

    next_id = 2
    while len(events) < event_count:
        action = CmdRunAction(command=f'echo chunk-{next_id}')
        action.id = next_id
        events.append(action)
        next_id += 1
        obs = CmdOutputObservation(
            content=f'output-{next_id - 1} ' + ('x' * 40),
            command=f'echo chunk-{next_id - 1}',
        )
        obs.id = next_id
        obs.cause = next_id - 1
        events.append(obs)
        next_id += 1
        if next_id % 50 == 0:
            msg = MessageAction(content=f'user checkpoint {next_id}')
            msg.source = EventSource.USER
            msg.id = next_id
            events.append(msg)
            next_id += 1

    return events


def test_large_history_windowing_preserves_summary_and_immutability() -> None:
    """800-event history must window without mutating source event content."""
    events = _build_large_history(800)
    summary = events[1]
    tail_obs = events[-1]
    original_tail_content = tail_obs.content

    cfg = SimpleNamespace(
        prompt_history_token_budget=500,
        prompt_history_min_events=1,
        prompt_history_max_events=40,
        model='gpt-4o',
    )
    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    assert result.original_events == len(events)
    assert result.selected_events <= 40
    assert summary in result.events
    assert tail_obs.content == original_tail_content
    assert events[-1].content == original_tail_content


def test_repeated_windowing_is_stable() -> None:
    """Repeated selection on the same history must return identical fingerprints."""
    events = _build_large_history(600)
    cfg = SimpleNamespace(
        prompt_history_token_budget=300,
        prompt_history_min_events=1,
        prompt_history_max_events=25,
        model='gpt-4o',
    )
    first = select_prompt_events(events, cfg)
    second = select_prompt_events(events, cfg)

    assert first.cache_fingerprint == second.cache_fingerprint
    assert first.selected_events == second.selected_events
    assert len(first.events) == len(second.events)
