"""Tests for backend.context.context_pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.context_pipeline import (
    ContextPipeline,
    _shrink_tail_for_token_reduction,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.compaction import (
    _CompactionEngine,
    mark_just_compacted,
    passes_effectiveness_gate,
    record_autocompact_failure,
    record_boundary_compact,
    resolve_continuity_or_fallback,
    should_skip_compaction,
)
from backend.context.context_pipeline.helpers import is_prewarm_stale
from backend.context.context_pipeline.types import (
    _AUTOCOMPACT_FAILURE_STREAK_KEY,
    _JUST_COMPACTED_KEY,
    _MAX_AUTOCOMPACT_FAILURES,
    _WILL_RETRIGGER_HYSTERESIS_KEY,
    _ContinuityGateDecision,
)
from backend.context.context_budget import ContextBudget
from backend.core.config.compactor_config import ContextPipelineConfig
from backend.core.constants import (
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
    DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS,
)
from backend.ledger.action.agent import CondensationAction
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
        config=ContextPipelineConfig(allow_llm_hot_path=False),
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
async def test_prepare_step_commits_degraded_boundary_when_over_threshold(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 402):
        events.append(_cmd_output(f'output line {i}\n' * 20, i))
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=8_000, model='test-model')
    state.agent = SimpleNamespace(llm=SimpleNamespace(config=llm_config))
    with (
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=False,
        ),
        patch('backend.context.context_pipeline.finalize_compaction_artifacts'),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch.object(pipeline, '_llm_config', return_value=llm_config),
    ):
        result = await pipeline.prepare_step(state)
    assert result.pending_action is not None
    assert isinstance(result.pending_action, CondensationAction)
    assert result.pending_action.summary
    assert len(result.pending_action.pruned) >= 20
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
            'backend.context.context_pipeline.pipeline.passes_effectiveness_gate',
            return_value=True,
        ),
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
        patch(
            'backend.context.context_pipeline.finalize_compaction_artifacts'
        ),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch(
            'backend.context.context_pipeline.pipeline.passes_effectiveness_gate',
            return_value=True,
        ),
    ):
        result = await pipeline.prepare_step(state)

    assert result.pending_action is not None
    assert result.pending_action.summary == action.summary
    assert len(result.events) < len(events)


@pytest.mark.asyncio
async def test_prepare_step_rejects_micro_prune_and_respects_cooldown(pipeline):
    """Ineffective 4-event prunes must not commit; cooldown blocks rapid re-compaction."""
    events = [_user('fix tests', 1)]
    for i in range(2, 52):
        events.append(_cmd_output(f'small {i}', i))
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='test-model')
    state.agent = SimpleNamespace(llm=SimpleNamespace(config=llm_config))

    with (
        patch(
            'backend.context.context_pipeline.compaction._select_compaction_tail',
            return_value=events[-47:],
        ),
        patch(
            'backend.context.context_pipeline.compaction._shrink_tail_for_token_reduction',
            side_effect=lambda _events, tail, **kwargs: tail,
        ),
        patch(
            'backend.context.context_pipeline.finalize_compaction_artifacts'
        ) as mock_finalize,
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
    ):
        with patch.object(pipeline, '_llm_config', return_value=llm_config):
            with patch(
                'backend.context.context_pipeline.ContextBudget.from_events',
                return_value=SimpleNamespace(
                    should_autocompact=True,
                    estimated_tokens=190_000,
                    autocompact_threshold=180_000,
                    effective_window=200_000,
                    fixed_prompt_reserve_tokens=500,
                    reserved_summary_tokens=100,
                ),
            ):
                first = await pipeline.prepare_step(state)
        assert first.pending_action is None
        mock_finalize.assert_not_called()

        state.extra_data['context_pipeline_state'] = {
            'last_boundary_compact_at': __import__('time').time(),
        }
        with patch.object(pipeline, '_llm_config', return_value=llm_config):
            with patch(
                'backend.context.context_pipeline.ContextBudget.from_events',
                return_value=SimpleNamespace(
                    should_autocompact=True,
                    estimated_tokens=190_000,
                    autocompact_threshold=180_000,
                    effective_window=200_000,
                    fixed_prompt_reserve_tokens=500,
                    reserved_summary_tokens=100,
                ),
            ):
                second = await pipeline.prepare_step(state)
        assert second.pending_action is None


def test_structured_compactor_preserves_50_raw_events():
    """With max_size=102, compaction keeps ~50 raw tail events."""
    from backend.context.compactor.strategies.structured_summary_compactor import (
        StructuredSummaryCompactor,
    )

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
async def test_run_compaction_falls_back_to_degraded_when_llm_exhausted():
    from backend.context.context_pipeline.types import _MAX_LLM_COMPACTION_ATTEMPTS

    events = [_user('fix context', 1)]
    for event_id in range(2, 80):
        events.append(_cmd_output(f'line {event_id}', event_id))
    state = _make_state(events)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=True),
    )
    degraded_action = CondensationAction(
        pruned_event_ids=list(range(2, 60)),
        summary='recovery summary',
        summary_offset=0,
    )
    budget = SimpleNamespace(
        should_autocompact=True,
        estimated_tokens=80_000,
        autocompact_threshold=70_000,
        fixed_prompt_reserve_tokens=0,
    )

    with (
        patch.object(
            pipeline._compaction_engine,
            '_llm_structured_compaction',
            new=AsyncMock(return_value=None),
        ) as mock_llm,
        patch.object(
            pipeline._compaction_engine,
            '_degraded_compaction',
            return_value=degraded_action,
        ) as mock_degraded,
    ):
        action = await pipeline._compaction_engine.run(
            state,
            events,
            events,
            budget,  # type: ignore[arg-type]
            llm_config=SimpleNamespace(model='test-model'),
            force=False,
            critical=False,
        )

    assert action is degraded_action
    assert mock_llm.await_count == _MAX_LLM_COMPACTION_ATTEMPTS
    mock_degraded.assert_called_once()


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


def test_passes_effectiveness_gate_uses_full_post_boundary_estimate() -> None:
    """Pruning old events must count even when API token cache is stale."""
    events = [_user('goal', 1)]
    for event_id in range(2, 80):
        events.append(_cmd_output('x' * 400, event_id))
    state = _make_state(
        events,
        extra={
            'prompt_token_accounting': {
                'static_prompt_tokens': 20_000,
                'tool_schema_tokens': 10_000,
                'context_packet_tokens': 500,
                'dynamic_history_tokens': 90_000,
            }
        },
    )
    state.metrics = MagicMock(
        token_usages=[MagicMock(prompt_tokens=120_000, total_tokens=125_000)]
    )
    llm_config = SimpleNamespace(model='gpt-test', max_input_tokens=200_000)
    budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
    action = CondensationAction(
        pruned_event_ids=list(range(2, 60)),
        summary='Condensed earlier tool output and file work.',
        summary_offset=0,
    )

    assert passes_effectiveness_gate(
        events, events, action, budget, state, llm_config
    )


def test_note_llm_step_does_not_clear_ineffective_compaction_backoff(pipeline):
    events = [_user('fix tests', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    apply_ineffective_compaction_backoff(state)
    pipe = state.extra_data['context_pipeline_state']
    skip_until = pipe['skip_compaction_until_event_id']
    streak = pipe['ineffective_compact_streak']

    pipeline.note_llm_step(state)

    after = state.extra_data['context_pipeline_state']
    assert after['skip_compaction_until_event_id'] == skip_until
    assert after['ineffective_compact_streak'] == streak
    assert after['consecutive_condensation_steps'] == 0


def test_ineffective_compaction_backoff_blocks_until_event_threshold(pipeline):
    events = [_user('fix tests', 1)]
    for i in range(2, 12):
        events.append(_cmd_output(f'line {i}', i))
    state = _make_state(events)
    latest_id = events[-1].id
    apply_ineffective_compaction_backoff(state)
    skip_until = state.extra_data['context_pipeline_state'][
        'skip_compaction_until_event_id'
    ]
    assert skip_until == latest_id + DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS
    assert (
        should_skip_compaction(state, pipeline._boundary_compact_cooldown, force=False)
        is True
    )

    # Still blocked before threshold.
    state.history.append(_cmd_output('mid', skip_until - 1))
    assert (
        should_skip_compaction(state, pipeline._boundary_compact_cooldown, force=False)
        is True
    )

    # Unblocked once latest id reaches skip_until (and time backoff expired).
    state.history.append(_cmd_output('past threshold', skip_until))
    pipe = state.extra_data['context_pipeline_state']
    pipe['ineffective_compact_until'] = 0
    state.extra_data['context_pipeline_state'] = pipe
    assert (
        should_skip_compaction(state, pipeline._boundary_compact_cooldown, force=False)
        is False
    )


def test_ineffective_compaction_backoff_escalates_streak(pipeline):
    events = [_user('fix tests', 1)]
    state = _make_state(events)
    apply_ineffective_compaction_backoff(state)
    first = state.extra_data['context_pipeline_state']['skip_compaction_until_event_id']
    apply_ineffective_compaction_backoff(state)
    second = state.extra_data['context_pipeline_state'][
        'skip_compaction_until_event_id'
    ]
    assert second > first


def test_shrink_tail_for_token_reduction_drops_oldest_events():
    events = [_user('task', 1)]
    for i in range(2, 52):
        events.append(_cmd_output(f'line {i}', i))
    llm_config = SimpleNamespace(max_input_tokens=200_000, model='test-model')
    state = _make_state(events)
    budget = SimpleNamespace(estimated_tokens=200_000)
    tail = list(events[-25:])
    summary = 'summary'

    reductions = [2_000, 4_000, 6_000, 12_000]
    calls: list[int] = []

    def fake_reduction(*_args, **_kwargs) -> int:
        value = reductions[min(len(calls), len(reductions) - 1)]
        calls.append(value)
        return value

    with patch(
        'backend.context.context_pipeline.helpers._projected_compaction_token_reduction',
        side_effect=fake_reduction,
    ):
        shrunk = _shrink_tail_for_token_reduction(
            events,
            tail,
            history=events,
            budget=budget,
            state=state,
            llm_config=llm_config,
            summary=summary,
        )

    assert len(shrunk) < len(tail)
    assert calls[-1] >= DEFAULT_COMPACT_MIN_TOKEN_REDUCTION
    assert len(calls) >= 3


def test_successful_boundary_compact_clears_ineffective_backoff(pipeline):
    events = [_user('fix tests', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    apply_ineffective_compaction_backoff(state)
    action = CondensationAction(
        pruned_event_ids=[1],
        summary='summary',
        summary_offset=0,
    )
    record_boundary_compact(state, events, action)
    pipe = state.extra_data['context_pipeline_state']
    assert 'skip_compaction_until_event_id' not in pipe
    assert 'ineffective_compact_streak' not in pipe
    assert 'ineffective_compact_until' not in pipe
    assert 'last_boundary_compact_at' in pipe


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
        patch('backend.context.context_pipeline.finalize_compaction_artifacts') as mock_finalize,
        patch('backend.context.context_pipeline.maybe_update'),
        patch.object(pipeline._compaction_engine, 'run', new=AsyncMock(return_value=None)),
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


def test_just_compacted_skips_autocompact_but_critical_force_bypasses(pipeline):
    events = [_user('task', 1)]
    state = _make_state(events)
    mark_just_compacted(state)
    assert (
        should_skip_compaction(
            state, pipeline._boundary_compact_cooldown, force=False, explicit=False
        )
        is True
    )
    assert (
        should_skip_compaction(
            state, pipeline._boundary_compact_cooldown, force=True, explicit=False
        )
        is False
    )
    assert (
        should_skip_compaction(
            state, pipeline._boundary_compact_cooldown, force=False, explicit=True
        )
        is False
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
            'backend.context.context_pipeline.pipeline.passes_effectiveness_gate',
            return_value=True,
        ),
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


def test_will_retrigger_hysteresis_is_telemetry_only_not_skip_gate(pipeline):
    events = [_user('task', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    action = CondensationAction(
        pruned_event_ids=[1],
        summary='huge summary ' * 5000,
        summary_offset=0,
    )
    budget = SimpleNamespace(autocompact_threshold=1000)
    llm_config = SimpleNamespace(model='test-model')
    with patch(
        'backend.context.context_pipeline.compaction.estimate_boundary_event_tokens',
        return_value=50_000,
    ):
        record_boundary_compact(
            state, events, action, budget=budget, llm_config=llm_config
        )
    pipe = state.extra_data['context_pipeline_state']
    assert pipe.get(_WILL_RETRIGGER_HYSTERESIS_KEY) is True
    # Cooldown from record_post_compact_baseline is unrelated to hysteresis telemetry.
    pipe['last_boundary_compact_at'] = 0
    state.extra_data['context_pipeline_state'] = pipe
    assert (
        should_skip_compaction(state, pipeline._boundary_compact_cooldown, force=True)
        is False
    )
    assert (
        should_skip_compaction(state, pipeline._boundary_compact_cooldown, force=False)
        is False
    )


def test_autocompact_circuit_breaker_blocks_skip_gate(pipeline):
    events = [_user('task', 1)]
    state = _make_state(events)
    for _ in range(_MAX_AUTOCOMPACT_FAILURES):
        record_autocompact_failure(state)
    assert (
        should_skip_compaction(state, pipeline._boundary_compact_cooldown, force=False)
        is True
    )


@pytest.mark.asyncio
async def test_ineffective_compact_does_not_loop_more_than_circuit_breaker(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 60):
        events.append(_cmd_output(f'output {i}', i))
    state = _make_state(events)
    llm_config = SimpleNamespace(max_input_tokens=8_000, model='test-model')
    pipeline._llm_config = MagicMock(return_value=llm_config)  # type: ignore[method-assign]

    with (
        patch('backend.context.context_pipeline.pipeline.ContextBudget') as mock_budget,
        patch.object(
            pipeline._compaction_engine,
            'run',
            new=AsyncMock(return_value=None),
        ) as run_mock,
        patch('backend.context.context_pipeline.maybe_update'),
    ):
        mock_budget.from_events.return_value = SimpleNamespace(
            should_autocompact=True,
            estimated_tokens=90_000,
            autocompact_threshold=70_000,
            effective_window=100_000,
            fixed_prompt_reserve_tokens=500,
            reserved_summary_tokens=100,
        )
        for _ in range(_MAX_AUTOCOMPACT_FAILURES + 1):
            await pipeline.prepare_step(state)

    assert run_mock.await_count == _MAX_AUTOCOMPACT_FAILURES
    pipe = state.extra_data['context_pipeline_state']
    assert pipe[_AUTOCOMPACT_FAILURE_STREAK_KEY] >= _MAX_AUTOCOMPACT_FAILURES
