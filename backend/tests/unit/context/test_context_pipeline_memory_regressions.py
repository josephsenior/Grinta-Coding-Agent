"""Regression tests for long-session context and compaction behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.context.canonical_state import (
    CanonicalTaskState,
    reduce_events_into_state,
    render_canonical_state_for_prompt,
)
from backend.context.compactor.pre_condensation_snapshot import extract_snapshot
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline import (
    ContextPipeline,
    _ContinuityGateDecision,
)
from backend.core.config.compactor_config import ContextPipelineConfig
from backend.core.constants import DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS
from backend.ledger.action.agent import AgentThinkAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation


def _user(text: str, event_id: int) -> MessageAction:
    action = MessageAction(content=text)
    action.id = event_id
    action.source = EventSource.USER
    return action


def _cmd(command: str, event_id: int) -> CmdRunAction:
    action = CmdRunAction(command=command)
    action.id = event_id
    return action


def _output(
    command: str, content: str, event_id: int, exit_code: int
) -> CmdOutputObservation:
    obs = CmdOutputObservation(content=content, command=command, exit_code=exit_code)
    obs.id = event_id
    return obs


def _state(events: list) -> MagicMock:
    state = MagicMock()
    state.history = events
    state.extra_data = {}
    state.session_id = 'test-session'
    state.view = MagicMock(unhandled_condensation_request=False)
    state.turn_signals = MagicMock(memory_pressure=None, prewarmed_compaction=None)

    def _set_extra(key: str, value: object, source: str = 'test') -> None:
        del source
        state.extra_data[key] = value

    state.set_extra = _set_extra

    def _set_memory_pressure(level: str, source: str = 'test') -> None:
        del source
        state.turn_signals.memory_pressure = level

    state.set_memory_pressure = _set_memory_pressure
    return state


def test_soak_replay_excerpt_recoverable_tool_error_is_not_durable() -> None:
    fixture = (
        Path(__file__).parents[2]
        / 'fixtures'
        / 'context_replay'
        / 'a37d423a-f04d-4d-1844cb8d0bf8821_excerpt.txt'
    )
    text = fixture.read_text(encoding='utf-8')
    events = [
        AgentThinkAction(thought=text),
        ErrorObservation(content=text),
    ]

    snapshot = extract_snapshot(events)

    assert 'Missing required argument "type"' in text
    assert snapshot['decisions'] == []
    assert snapshot['recent_errors'] == []
    assert snapshot['attempted_approaches'] == []


def test_deterministic_fallback_commits_after_repeated_equivalent_rejection(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [_user('Fix the context pipeline regression', 1)]
    for event_id in range(2, 122, 2):
        events.append(_cmd(f'pytest chunk-{event_id}', event_id))
        events.append(
            _output(
                f'pytest chunk-{event_id}',
                ('failed output line\n' * 30),
                event_id + 1,
                1,
            )
        )
    state = _state(events)
    reduce_events_into_state(events, CanonicalTaskState(), state=state, persist=True)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=False),
    )
    decision = _ContinuityGateDecision(
        passed=False,
        canonical_ok=True,
        fingerprint='continuity:stale-tool-schema',
        missing=('decision:Missing required argument "type"',),
        score=0.98,
        matched=105,
        total=107,
    )
    budget = ContextBudget(
        estimated_tokens=80_000,
        effective_window=100_000,
        autocompact_threshold=70_000,
    )
    llm_config = SimpleNamespace(
        model='openai/gpt-4.1',
        context_window_tokens=1_047_576,
        max_output_tokens=32_768,
    )

    with patch.object(pipeline, '_passes_effectiveness_gate', return_value=True):
        first = pipeline._deterministic_fallback_after_rejection(
            state,
            events,
            events,
            budget,
            llm_config,
            decision,
        )
        second = pipeline._deterministic_fallback_after_rejection(
            state,
            events,
            events,
            budget,
            llm_config,
            decision,
        )

    assert first is None
    assert second is not None
    assert len(second.pruned) >= 20
    assert 'Canonical task state' in (second.summary or '')
    assert (
        'continuity_rejection_streak' not in state.extra_data['context_pipeline_state']
    )


def test_recent_work_ledger_renders_once_for_latest_verification() -> None:
    events = [
        _user('Fix prompt history collapse', 1),
        _cmd('pytest backend/tests/unit/context', 2),
        _output('pytest backend/tests/unit/context', '3 failed', 3, 1),
        _cmd('pytest backend/tests/unit/context', 4),
        _output('pytest backend/tests/unit/context', '10 passed', 5, 0),
    ]

    canonical = reduce_events_into_state(events, CanonicalTaskState(), persist=False)
    rendered = render_canonical_state_for_prompt(canonical, char_budget=2000)

    assert rendered.count('Latest verification:') == 1
    assert 'Recent work ledger' in rendered
    assert 'pytest backend/tests/unit/context' in rendered


def test_emergency_prompt_window_refuses_single_digit_collapse() -> None:
    events = [_user('Keep enough recent work visible', 1)]
    for event_id in range(2, 90, 2):
        events.append(_cmd(f'echo {event_id}', event_id))
        events.append(_output(f'echo {event_id}', 'payload ' * 300, event_id + 1, 0))
    state = _state(events)
    llm_config = SimpleNamespace(
        model='tiny-local-model',
        prompt_history_token_budget=30,
        prompt_history_min_events=1,
        prompt_history_max_events=None,
        prompt_history_min_tool_loops=0,
        prompt_history_min_tail_tokens=0,
    )
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=False),
    )

    result = pipeline.build_prompt_events(
        events,
        state=state,
        llm_config=llm_config,
        full_history=events,
    )

    assert len(result) >= DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS
    assert state.turn_signals.memory_pressure == 'CRITICAL'
