"""Tests for token-budget-aware prompt event windowing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.context.prompt_window import select_prompt_events
from backend.ledger.action import CmdRunAction, MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation import CmdOutputObservation
from backend.ledger.observation.agent import AgentCondensationObservation


@pytest.fixture(autouse=True)
def _isolate_durable_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.context.pre_condensation_snapshot.load_snapshot',
        lambda: None,
    )
    monkeypatch.setattr(
        'backend.engine.tools.working_memory.get_working_memory_prompt_block',
        lambda char_budget=2000: '',
    )


def _with_id(event: Event, event_id: int) -> Event:
    event.id = event_id
    return event


def _user_message(text: str, event_id: int) -> MessageAction:
    event = MessageAction(content=text)
    event.source = EventSource.USER
    return _with_id(event, event_id)  # type: ignore[return-value]


def _run_chunk(event_id: int, label: str, payload: str = '') -> list[Event]:
    action = _with_id(CmdRunAction(command=f'echo {label}'), event_id)
    observation = _with_id(
        CmdOutputObservation(content=payload or f'output {label}', command=f'echo {label}'),
        event_id + 1,
    )
    return [action, observation]


def test_returns_full_history_when_within_budget() -> None:
    events = [_user_message('start', 1), *_run_chunk(2, 'small')]
    cfg = SimpleNamespace(
        prompt_history_token_budget=10_000,
        prompt_history_min_events=1,
        prompt_history_max_events=100,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert result.windowed is False
    assert result.events == events


def test_window_preserves_summary_and_recent_action_observation_chunk() -> None:
    summary = _with_id(
        AgentCondensationObservation(content='summary of older work'),
        2,
    )
    old_chunk = _run_chunk(3, 'old', payload='old payload ' * 200)
    recent_chunk = _run_chunk(101, 'recent', payload='recent payload')
    events = [_user_message('start', 1), summary, *old_chunk, *recent_chunk]
    cfg = SimpleNamespace(
        prompt_history_token_budget=80,
        prompt_history_min_events=1,
        prompt_history_max_events=10,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    assert summary in result.events
    assert recent_chunk[0] in result.events
    assert old_chunk[0] not in result.events
    assert old_chunk[1] not in result.events


def test_window_protects_only_latest_real_condensation_summary() -> None:
    old_summary = _with_id(
        AgentCondensationObservation(content='old condensed summary'),
        2,
    )
    restore = _with_id(
        AgentCondensationObservation(
            content='<POST_COMPACT_RESTORE>\nold restore\n</POST_COMPACT_RESTORE>'
        ),
        3,
    )
    latest_summary = _with_id(
        AgentCondensationObservation(content='latest condensed summary'),
        4,
    )
    old_chunk = _run_chunk(5, 'old', payload='old payload ' * 200)
    recent_chunk = _run_chunk(101, 'recent', payload='recent payload')
    events = [
        _user_message('start', 1),
        old_summary,
        restore,
        latest_summary,
        *old_chunk,
        *recent_chunk,
    ]
    cfg = SimpleNamespace(
        prompt_history_token_budget=90,
        prompt_history_min_events=1,
        prompt_history_max_events=10,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert latest_summary in result.events
    assert old_summary not in result.events
    assert restore not in result.events


def test_event_count_guard_windows_many_tiny_events_without_token_budget() -> None:
    events = [_user_message('start', 1)]
    for idx in range(2, 30, 2):
        events.extend(_run_chunk(idx, f'cmd-{idx}', payload='ok'))
    cfg = SimpleNamespace(
        prompt_history_token_budget=None,
        max_input_tokens=None,
        prompt_history_min_events=1,
        prompt_history_max_events=6,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    assert result.selected_events <= 6
    assert events[-2] in result.events
    assert events[-1] in result.events


def test_windowing_does_not_mutate_input_event_content() -> None:
    long_payload = 'x' * 5000
    events = [_user_message('start', 1), *_run_chunk(2, 'big', payload=long_payload)]
    original_content = events[-1].content
    cfg = SimpleNamespace(
        prompt_history_token_budget=40,
        prompt_history_min_events=1,
        prompt_history_max_events=4,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    assert events[-1].content == original_content


def test_token_ceiling_trims_oversized_latest_chunk() -> None:
    huge = 'payload ' * 800
    events = [_user_message('start', 1), *_run_chunk(2, 'huge', payload=huge)]
    cfg = SimpleNamespace(
        prompt_history_token_budget=350,
        prompt_history_min_events=1,
        prompt_history_max_events=100,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    assert result.selected_estimated_tokens < result.estimated_tokens
    assert result.selected_estimated_tokens <= result.token_budget
    obs_events = [
        event
        for event in result.events
        if type(event).__name__ == 'CmdOutputObservation'
    ]
    if obs_events:
        assert '[... truncated' in str(obs_events[0].content)


def test_window_preserves_first_and_last_user_messages() -> None:
    first = _user_message('build raftkv', 1)
    middle = _user_message('status update', 3)
    last = _user_message('continue fixing tests', 99)
    old_chunk = _run_chunk(5, 'old', payload='old payload ' * 200)
    recent_chunk = _run_chunk(101, 'recent', payload='recent payload')
    events = [first, middle, *old_chunk, last, *recent_chunk]
    cfg = SimpleNamespace(
        prompt_history_token_budget=120,
        prompt_history_min_events=1,
        prompt_history_max_events=8,
        prompt_history_min_tool_loops=1,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert first in result.events
    assert last in result.events


def test_window_enforces_minimum_tool_loops() -> None:
    events = [_user_message('start', 1)]
    for idx in range(2, 40, 2):
        events.extend(_run_chunk(idx, f'cmd-{idx}', payload='ok'))
    cfg = SimpleNamespace(
        prompt_history_token_budget=10_000,
        prompt_history_min_events=1,
        prompt_history_max_events=6,
        prompt_history_min_tool_loops=3,
        prompt_history_min_tail_tokens=0,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    chunk_count = sum(
        1
        for event in result.events
        if isinstance(event, CmdRunAction)
    )
    assert chunk_count >= 3


def test_orphan_action_without_observation_is_dropped_as_causal_unit() -> None:
    orphan_action = _with_id(CmdRunAction(command='echo orphan'), 10)
    recent_chunk = _run_chunk(12, 'recent', payload='recent payload')
    events = [_user_message('start', 1), orphan_action, *recent_chunk]
    cfg = SimpleNamespace(
        prompt_history_token_budget=60,
        prompt_history_min_events=1,
        prompt_history_max_events=4,
        model='gpt-4o',
    )

    result = select_prompt_events(events, cfg)

    assert orphan_action not in result.events
    assert recent_chunk[0] in result.events
