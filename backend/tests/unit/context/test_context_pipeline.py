"""Tests for backend.context.context_pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compact_boundary import (
    find_last_condensation_action,
    find_pending_condensation_request,
)
from backend.context.compactor.compactor import Compaction
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline import ContextPipeline
from backend.context.context_pipeline.compaction import (
    dismiss_explicit_compaction_request,
    has_actionable_explicit_request,
    mark_just_compacted,
    passes_effectiveness_gate,
    record_boundary_compact,
    resolve_continuity_or_fallback,
    should_run_compaction,
    should_skip_compaction,
)
from backend.context.context_pipeline.helpers import is_prewarm_stale
from backend.context.context_pipeline.types import _ContinuityGateDecision
from backend.core.config.compactor_config import ContextPipelineConfig
from backend.ledger.action.agent import CondensationAction, CondensationRequestAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation


def _make_state(events: list, *, extra: dict | None = None) -> MagicMock:
    state = MagicMock()
    state.history = events
    state.extra_data = extra or {}
    state.view = MagicMock(unhandled_condensation_request=False)
    state.turn_signals = MagicMock(memory_pressure=None, prewarmed_compaction=None)
    state.ack_memory_pressure = MagicMock()
    state.agent = None
    state.session_id = 'test-session'
    state.iteration_flag = None

    def _set_extra(key, value, source='test'):
        state.extra_data[key] = value

    state.set_extra = _set_extra
    return state


def _user(text: str, event_id: int) -> MessageAction:
    action = MessageAction(content=text)
    action.id = event_id
    action.source = EventSource.USER
    return action


def _cmd_output(text: str, event_id: int) -> CmdOutputObservation:
    obs = CmdOutputObservation(content=text, command='pytest', metadata={})
    obs.id = event_id
    return obs


@pytest.fixture
def pipeline() -> ContextPipeline:
    return ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(),
    )


@pytest.fixture(autouse=True)
def _isolate_snapshot_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.context.compactor.pre_condensation_snapshot._snapshot_path',
        lambda state=None: tmp_path / 'pre_condensation_snapshot.json',
    )
    monkeypatch.setattr(
        'backend.context.compactor.pre_condensation_snapshot._snapshot_staging_path',
        lambda state=None: tmp_path / '.pre_condensation_snapshot.staging.json',
    )
    monkeypatch.setattr(
        'backend.context.memory.session_memory._session_memory_path',
        lambda state=None: tmp_path / 'session_memory.md',
    )
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )


@pytest.mark.asyncio
async def test_prepare_step_skips_compaction_under_threshold(pipeline):
    events = [_user('fix tests', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    with patch('backend.context.context_pipeline.ContextBudget') as mock_budget:
        mock_budget.from_events.return_value = SimpleNamespace(
            should_autocompact=False,
            estimated_tokens=100,
            autocompact_threshold=1000,
            effective_window=2000,
            fixed_prompt_reserve_tokens=500,
            reserved_summary_tokens=100,
        )
        result = await pipeline.prepare_step(state)
    assert result.pending_action is None
    assert result.events == events


@pytest.mark.asyncio
async def test_prepare_step_commits_llm_compaction_when_over_threshold(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 402):
        events.append(_cmd_output(f'output line {i}\n' * 20, i))
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=8_000, model='test-model')
    state.agent = SimpleNamespace(llm=SimpleNamespace(config=llm_config))
    llm_action = CondensationAction(
        pruned_event_ids=list(range(2, 182)),
        summary='LLM compaction summary ' * 50,
        summary_offset=0,
    )
    with (
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=False,
        ),
        patch('backend.context.context_pipeline.finalize_compaction_artifacts'),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch.object(pipeline, '_llm_config', return_value=llm_config),
        patch.object(
            pipeline._compaction_engine,
            'run',
            new=AsyncMock(return_value=llm_action),
        ),
    ):
        result = await pipeline.prepare_step(state)
    assert result.pending_action is not None
    assert isinstance(result.pending_action, CondensationAction)
    assert result.pending_action.summary
    assert result.events == []


@pytest.mark.asyncio
async def test_prepare_step_uses_prewarmed_compaction(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 202):
        events.append(_cmd_output(f'output line {i}\n' * 20, i))
    action = CondensationAction(
        pruned_event_ids=list(range(2, 182)),
        summary='prewarmed summary ' * 200,
        summary_offset=0,
    )
    prewarmed = Compaction(action=action)
    state = _make_state(events)
    state.turn_signals.prewarmed_compaction = prewarmed
    with (
        patch('backend.context.context_pipeline.finalize_compaction_artifacts'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch(
            'backend.context.context_pipeline.pipeline.resolve_continuity_or_fallback',
            return_value=action,
        ),
    ):
        result = await pipeline.prepare_step(state)
    assert result.pending_action is action
    assert result.events == []


@pytest.mark.asyncio
async def test_prepare_step_accepts_prewarmed_compaction_despite_continuity_issues(
    pipeline,
):
    events = [_user('run pytest', 1)]
    for i in range(2, 202):
        events.append(_cmd_output(f'output line {i}\n' * 20, i))
    action = CondensationAction(
        pruned_event_ids=list(range(2, 182)),
        summary='prewarmed summary ' * 200,
        summary_offset=0,
    )
    state = _make_state(events)
    state.turn_signals.prewarmed_compaction = Compaction(action=action)
    with (
        patch('backend.context.context_pipeline.finalize_compaction_artifacts'),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
    ):
        result = await pipeline.prepare_step(state)

    assert result.pending_action is not None
    assert result.pending_action.summary == action.summary
    assert len(result.events) < len(events)



def test_structured_compactor_preserves_50_raw_events():
    """With max_size=102, compaction keeps ~50 raw tail events."""
    compactor = SimpleNamespace(max_size=102, keep_first=0)

    target_size = compactor.max_size // 2
    events_from_tail = target_size - compactor.keep_first - 1
    assert events_from_tail == 50


@pytest.mark.asyncio
async def test_run_compaction_uses_llm_structured_compaction_when_available():
    events = [_user('fix context', 1)]
    for event_id in range(2, 80):
        events.append(_cmd_output(f'line {event_id}', event_id))
    state = _make_state(events)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=True),
    )
    llm_action = CondensationAction(
        pruned_event_ids=list(range(2, 60)),
        summary='structured summary',
        summary_offset=0,
    )
    budget = SimpleNamespace(
        should_autocompact=True,
        estimated_tokens=80_000,
        autocompact_threshold=70_000,
        fixed_prompt_reserve_tokens=0,
    )

    with patch.object(
        pipeline._compaction_engine,
        '_llm_structured_compaction',
        new=AsyncMock(return_value=llm_action),
    ) as mock_llm:
        action = await pipeline._compaction_engine.run(
            state,
            events,
            events,
            budget,  # type: ignore[arg-type]
            llm_config=SimpleNamespace(model='test-model'),
            force=False,
            critical=False,
        )

    assert action is llm_action
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_compaction_returns_none_when_llm_exhausted():
    from backend.context.context_pipeline.types import _MAX_LLM_COMPACTION_ATTEMPTS

    events = [_user('fix context', 1)]
    for event_id in range(2, 80):
        events.append(_cmd_output(f'line {event_id}', event_id))
    state = _make_state(events)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(),
    )
    budget = SimpleNamespace(
        should_autocompact=True,
        estimated_tokens=80_000,
        autocompact_threshold=70_000,
        fixed_prompt_reserve_tokens=0,
    )

    with patch.object(
        pipeline._compaction_engine,
        '_llm_structured_compaction',
        new=AsyncMock(return_value=None),
    ) as mock_llm:
        action = await pipeline._compaction_engine.run(
            state,
            events,
            events,
            budget,  # type: ignore[arg-type]
            llm_config=SimpleNamespace(model='test-model'),
            force=False,
            critical=False,
        )

    assert action is None
    assert mock_llm.await_count == _MAX_LLM_COMPACTION_ATTEMPTS


def test_build_prompt_events_injects_context_packet(pipeline):
    events = [_user('implement feature X', 1)]
    state = _make_state(events)

    prompt_events = pipeline.build_prompt_events(events, state=state, llm_config=None)

    from backend.ledger.observation.agent import AgentCondensationObservation

    packet = prompt_events[0]
    assert isinstance(packet, AgentCondensationObservation)
    assert packet.is_working_set is True
    assert '<CONTEXT_PACKET>' in packet.content
    # User turns already in the prompt tail must not be duplicated in the packet.
    assert 'RECENT_USER_REQUEST_CONTEXT' not in packet.content
    assert 'implement feature X' not in packet.content
    assert any(
        isinstance(event, MessageAction) and event.content == 'implement feature X'
        for event in prompt_events
    )


def test_build_prompt_events_injects_context_packet_on_fresh_session(
    pipeline, monkeypatch, tmp_path
):
    events = [_user('Build a raft kv store', 1)]
    state = _make_state(events)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    from backend.engine.tools.working_memory import set_current_session_id

    set_current_session_id('fresh-session-1')

    prompt_events = pipeline.build_prompt_events(events, state=state, llm_config=None)

    from backend.ledger.observation.agent import AgentCondensationObservation

    packet = prompt_events[0]
    assert isinstance(packet, AgentCondensationObservation)
    assert packet.is_working_set is True
    assert '<CONTEXT_PACKET>' in packet.content
    assert 'RECENT_USER_REQUEST_CONTEXT' not in packet.content
    assert 'Build a raft kv store' not in packet.content
    assert any(
        isinstance(event, MessageAction) and event.content == 'Build a raft kv store'
        for event in prompt_events
    )


def test_passes_effectiveness_gate_accepts_nonempty_llm_summary() -> None:
    events = [_user('goal', 1)]
    state = _make_state(events)
    budget = SimpleNamespace(estimated_tokens=100_000)
    action = CondensationAction(
        pruned_event_ids=[],
        summary='Condensed earlier tool output and file work.',
        summary_offset=0,
    )

    assert passes_effectiveness_gate(events, events, action, budget, state, None)


def test_passes_effectiveness_gate_rejects_empty_summary() -> None:
    events = [_user('goal', 1)]
    state = _make_state(events)
    budget = SimpleNamespace(estimated_tokens=100_000)
    action = CondensationAction(
        pruned_event_ids=list(range(2, 60)),
        summary='',
        summary_offset=0,
    )

    assert not passes_effectiveness_gate(events, events, action, budget, state, None)


def test_resolve_continuity_or_fallback_logs_without_crash_on_canonical_failure():
    events = [_user('goal', 1)]
    state = _make_state(events)
    action = CondensationAction(
        pruned_event_ids=[1],
        summary='summary text ' * 200,
        summary_offset=0,
    )
    budget = SimpleNamespace(estimated_tokens=100_000)
    decision = _ContinuityGateDecision(
        passed=False,
        canonical_ok=False,
        fingerprint='canonical:latest_directive',
        missing=('latest_directive',),
        score=0.5,
        matched=1,
        total=2,
    )
    with patch(
        'backend.context.context_pipeline.compaction.evaluate_continuity_gate',
        return_value=decision,
    ):
        result = resolve_continuity_or_fallback(
            state, events, events, action, budget, None
        )
    assert result is action


def test_is_prewarm_stale_detects_history_growth():
    events = [_user('a', 1), _cmd_output('b', 2)]
    turn_signals = SimpleNamespace(
        prewarm_history_len=1,
        prewarm_latest_event_id=1,
    )
    assert is_prewarm_stale(events, turn_signals) is True


def test_is_prewarm_stale_false_when_metadata_matches():
    events = [_user('a', 1), _cmd_output('b', 2)]
    turn_signals = SimpleNamespace(
        prewarm_history_len=2,
        prewarm_latest_event_id=2,
    )
    assert is_prewarm_stale(events, turn_signals) is False


@pytest.mark.asyncio
async def test_prepare_step_discards_stale_prewarmed_compaction(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 52):
        events.append(_cmd_output(f'output {i}', i))
    action = CondensationAction(
        pruned_event_ids=list(range(2, 42)),
        summary='prewarmed summary ' * 200,
        summary_offset=0,
    )
    state = _make_state(events)
    state.turn_signals.prewarmed_compaction = Compaction(action=action)
    state.turn_signals.prewarm_history_len = 10
    state.turn_signals.prewarm_latest_event_id = 10
    with (
        patch(
            'backend.context.context_pipeline.finalize_compaction_artifacts'
        ) as mock_finalize,
        patch('backend.context.context_pipeline.maybe_update'),
        patch.object(
            pipeline._compaction_engine, 'run', new=AsyncMock(return_value=None)
        ),
    ):
        result = await pipeline.prepare_step(state)
    mock_finalize.assert_not_called()
    assert result.pending_action is None
    assert state.turn_signals.prewarmed_compaction is None


def test_should_emit_compaction_status_true_when_prewarmed(pipeline):
    action = CondensationAction(
        pruned_event_ids=[2, 3],
        summary='summary',
        summary_offset=0,
    )
    state = _make_state([_user('hello', 1)])
    state.turn_signals.prewarmed_compaction = Compaction(action=action)
    assert pipeline.should_emit_compaction_status(state) is True


def test_just_compacted_skips_autocompact_but_explicit_bypasses(pipeline):
    events = [_user('task', 1)]
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='test-model')
    budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
    mark_just_compacted(state)
    assert should_skip_compaction(
        state,
        events=events,
        llm_config=llm_config,
        history=list(state.history),
        explicit=False,
    )
    assert not should_skip_compaction(
        state,
        events=events,
        llm_config=llm_config,
        history=list(state.history),
        explicit=True,
    )
    assert not should_run_compaction(
        state,
        events=events,
        budget=budget,
        history=list(state.history),
        llm_config=llm_config,
        explicit=False,
    )
    assert should_run_compaction(
        state,
        events=events,
        budget=budget,
        history=list(state.history),
        llm_config=llm_config,
        explicit=True,
    )


@pytest.mark.asyncio
async def test_prepare_step_never_compacts_twice_before_llm_step(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 102):
        events.append(_cmd_output(f'output line {i}\n' * 20, i))
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=8_000, model='test-model')
    pipeline._llm_config = MagicMock(return_value=llm_config)  # type: ignore[method-assign]
    action = CondensationAction(
        pruned_event_ids=list(range(2, 80)),
        summary='boundary summary ' * 200,
        summary_offset=0,
    )
    run_mock = AsyncMock(return_value=action)

    with (
        patch('backend.context.context_pipeline.pipeline.ContextBudget') as mock_budget,
        patch.object(pipeline._compaction_engine, 'run', new=run_mock),
        patch('backend.context.context_pipeline.finalize_compaction_artifacts'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch(
            'backend.context.context_pipeline.pipeline.resolve_continuity_or_fallback',
            side_effect=lambda _s, _h, _e, action, *_a, **_k: action,
        ),
    ):
        mock_budget.from_events.return_value = SimpleNamespace(
            should_autocompact=True,
            estimated_tokens=90_000,
            autocompact_threshold=70_000,
            effective_window=100_000,
            fixed_prompt_reserve_tokens=500,
            reserved_summary_tokens=100,
        )
        first = await pipeline.prepare_step(state)
        second = await pipeline.prepare_step(state)

    assert first.pending_action is not None
    assert second.pending_action is None
    run_mock.assert_awaited_once()


def test_skip_compaction_when_boundary_at_or_below_snapshot(pipeline):
    """Do not re-compact until projected boundary tokens grow past the snapshot."""
    events = [_user('task', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    action = CondensationAction(
        pruned_event_ids=[1],
        summary='summary',
        summary_offset=0,
    )
    llm_config = SimpleNamespace(model='test-model')
    history = list(state.history)
    # Simulate CondensationAction already committed to history.
    state.history.append(action)
    with patch(
        'backend.context.context_pipeline.compaction.estimate_boundary_event_tokens',
        return_value=50_000,
    ):
        record_boundary_compact(
            state, events, action, llm_config=llm_config,
        )
        assert should_skip_compaction(
            state,
            events=events,
            llm_config=llm_config,
            history=history + [action],
        ) is True

    with patch(
        'backend.context.context_pipeline.compaction.estimate_boundary_event_tokens',
        return_value=55_000,
    ):
        assert should_skip_compaction(
            state,
            events=events,
            llm_config=llm_config,
            history=history + [action],
        ) is False


def test_skip_compaction_when_snapshot_set_but_boundary_not_in_history(pipeline):
    """Avoid stacking LLM compactions before CondensationAction lands in history."""
    events = [_user('task', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    action = CondensationAction(
        pruned_event_ids=[1],
        summary='summary',
        summary_offset=0,
    )
    llm_config = SimpleNamespace(model='test-model')
    with patch(
        'backend.context.context_pipeline.compaction.estimate_boundary_event_tokens',
        return_value=50_000,
    ):
        record_boundary_compact(
            state, events, action, llm_config=llm_config,
        )
    assert find_last_condensation_action(state.history) is None
    assert should_skip_compaction(
        state,
        events=events,
        llm_config=llm_config,
        history=list(state.history),
    ) is True


def test_dismissed_explicit_request_does_not_retrigger_compaction():
    """Failed explicit compaction must not loop on every subsequent step."""
    events = [_user('task', 1)]
    request = CondensationRequestAction()
    request.id = 99
    events.append(request)
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='test-model')
    budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)

    assert find_pending_condensation_request(state.history) is request
    assert has_actionable_explicit_request(state, state.history) is True
    assert should_run_compaction(
        state,
        events=events,
        budget=budget,
        history=list(state.history),
        llm_config=llm_config,
        explicit=True,
    )

    dismiss_explicit_compaction_request(state, state.history)

    assert has_actionable_explicit_request(state, state.history) is False
    assert not should_run_compaction(
        state,
        events=events,
        budget=budget,
        history=list(state.history),
        llm_config=llm_config,
        explicit=False,
    )

