"""Trajectory regression harness.

This harness validates recorded Grinta trajectories to catch reliability drift
between releases. It is opt-in and runs only when
`APP_TRAJECTORY_REGRESSION_DIR` points to a directory containing JSON
trajectory files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


def _get_regression_dir() -> Path | None:
    raw = os.getenv('APP_TRAJECTORY_REGRESSION_DIR', '').strip()
    if raw:
        path = Path(raw)
        if path.exists() and path.is_dir():
            return path

    # Default to a minimal baseline directory committed to the repo so this
    # regression harness runs in CI without extra environment configuration.
    default_dir = (
        Path(__file__).resolve().parents[1] / 'fixtures' / 'trajectory_regression'
    )
    if default_dir.exists() and default_dir.is_dir():
        return default_dir
    return None


def _iter_json_files(path: Path) -> list[Path]:
    files = sorted(path.rglob('*.json'))
    return [f for f in files if f.is_file()]


def _extract_events(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('events', 'history', 'trajectory'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _collect_agent_states(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        state = obj.get('agent_state')
        if isinstance(state, str):
            out.append(state.lower())
        for value in obj.values():
            _collect_agent_states(value, out)
        return
    if isinstance(obj, list):
        for item in obj:
            _collect_agent_states(item, out)


def _contains_error_markers(payload: Any) -> bool:
    text = json.dumps(payload, ensure_ascii=False).lower()
    markers = (
        'circuit breaker tripped',
        'action verification failed',
        'task_validation_failed',
    )
    return any(marker in text for marker in markers)


def pytest_generate_tests(metafunc):
    if 'trajectory_file' not in metafunc.fixturenames:
        return

    base = _get_regression_dir()
    if base is None:
        metafunc.parametrize('trajectory_file', [])
        return

    files = _iter_json_files(base)
    metafunc.parametrize('trajectory_file', files, ids=[f.name for f in files])


@pytest.mark.integration
def test_long_history_baseline_checks() -> None:
    """Programmatic long-history harness without a committed 500-event fixture."""
    from types import SimpleNamespace

    from backend.context.prompt.prompt_window import select_prompt_events
    from backend.ledger.action import CmdRunAction, MessageAction
    from backend.ledger.event import EventSource
    from backend.ledger.observation import CmdOutputObservation
    from backend.ledger.observation.agent import AgentCondensationObservation

    events: list[Any] = []
    events.append(MessageAction(content='start the long session task'))
    events[-1].source = EventSource.USER
    events[-1].id = 0

    next_id = 1
    while len(events) < 500:
        action = CmdRunAction(command=f'echo cmd-{next_id}')
        action.id = next_id
        events.append(action)
        next_id += 1
        obs = CmdOutputObservation(
            content=f'output cmd-{next_id - 1}',
            command=f'echo cmd-{next_id - 1}',
        )
        obs.id = next_id
        obs.cause = next_id - 1
        events.append(obs)
        next_id += 1
        if next_id % 40 == 0:
            msg = MessageAction(content=f'checkpoint user message {next_id}')
            msg.source = EventSource.USER
            msg.id = next_id
            events.append(msg)
            next_id += 1

    summary = AgentCondensationObservation(content='summary of older work')
    summary.id = 999
    events.insert(1, summary)

    start_msg = events[0]
    checkpoint_msgs = [
        event
        for event in events
        if isinstance(event, MessageAction)
        and event.source == EventSource.USER
        and event is not start_msg
    ]
    original_checkpoint_contents = [msg.content for msg in checkpoint_msgs]

    cfg = SimpleNamespace(
        prompt_history_token_budget=10_000,
        prompt_history_min_events=1,
        prompt_history_max_events=80,
        model='gpt-4o',
    )
    result = select_prompt_events(events, cfg)

    assert result.windowed is True
    assert result.selected_events <= 80
    assert summary in result.events
    assert start_msg.content == 'start the long session task'
    for original in original_checkpoint_contents:
        assert any(
            isinstance(event, MessageAction)
            and event.source == EventSource.USER
            and event.content == original
            for event in events
        ), 'Windowing must not mutate user message content in history'


@pytest.mark.integration
def test_trajectory_regression(trajectory_file: Path) -> None:
    """Validate a recorded trajectory against baseline reliability checks."""
    with trajectory_file.open('r', encoding='utf-8') as fh:
        payload = json.load(fh)

    events = _extract_events(payload)
    assert events, f'Trajectory has no events: {trajectory_file}'

    states: list[str] = []
    _collect_agent_states(payload, states)
    if states:
        assert states[-1] != 'error', (
            f'Trajectory ended in ERROR state: {trajectory_file} '
            f'(states tail={states[-5:]})'
        )

    assert not _contains_error_markers(payload), (
        f'Reliability error marker detected in trajectory: {trajectory_file}'
    )
