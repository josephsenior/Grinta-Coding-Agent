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
        'backend.context.pre_condensation_snapshot._snapshot_path',
        lambda state=None: tmp_path / 'pre_condensation_snapshot.json',
    )
    monkeypatch.setattr(
        'backend.context.pre_condensation_snapshot._snapshot_staging_path',
        lambda state=None: tmp_path / '.pre_condensation_snapshot.staging.json',
    )
    monkeypatch.setattr(
        'backend.context.session_memory._session_memory_path',
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
    ):
        result = await pipeline.prepare_step(state)
    assert result.pending_action is action
    assert result.events == []


@pytest.mark.asyncio
async def test_prepare_step_rejects_prewarmed_compaction_that_fails_continuity(
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
        ) as mock_finalize,
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch.object(pipeline, '_passes_effectiveness_gate', return_value=True),
        patch.object(pipeline, '_passes_continuity_gate', return_value=False),
    ):
        result = await pipeline.prepare_step(state)

    assert result.pending_action is None
    assert result.events == events
    mock_finalize.assert_not_called()


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
            'backend.context.context_pipeline.session_memory_exists', return_value=True
        ),
        patch(
            'backend.context.context_pipeline.build_compaction_summary',
            return_value='# Session Memory\nsummary',
        ),
        patch(
            'backend.context.context_pipeline._select_compaction_tail',
            return_value=events[-47:],
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
                ),
            ):
                second = await pipeline.prepare_step(state)
        assert second.pending_action is None


def test_configure_structured_compactor_size_forces_material_prune():
    """Regression: fixed max_size=100 left ~49 post-boundary events with zero pruned (5b no-op)."""
    events = [_cmd_output(f'line {i}', i) for i in range(1, 50)]
    compactor = SimpleNamespace(max_size=100, keep_first=0)
    ContextPipeline._configure_structured_compactor_size(
        compactor, events, SimpleNamespace()
    )

    target_size = compactor.max_size // 2
    events_from_tail = target_size - compactor.keep_first - 1
    tail_count = max(0, events_from_tail)
    stop = len(events) - tail_count if tail_count else len(events)
    pruned_count = stop - compactor.keep_first
    assert pruned_count >= 20


@pytest.mark.asyncio
async def test_run_compaction_tries_structured_llm_before_session_memory():
    events = [_user('fix context', 1)]
    for event_id in range(2, 80):
        events.append(_cmd_output(f'line {event_id}', event_id))
    state = _make_state(events)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=True),
        llm_compact_cooldown_seconds=0,
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

    with (
        patch.object(
            pipeline,
            '_llm_structured_compaction',
            new=AsyncMock(return_value=llm_action),
        ) as mock_llm,
        patch.object(pipeline, '_session_memory_compaction') as mock_session,
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=True,
        ),
    ):
        action = await pipeline._run_compaction(
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
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_run_compaction_uses_session_memory_only_as_fallback():
    events = [_user('fix context', 1)]
    for event_id in range(2, 80):
        events.append(_cmd_output(f'line {event_id}', event_id))
    state = _make_state(events)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=True),
        llm_compact_cooldown_seconds=0,
    )
    session_action = CondensationAction(
        pruned_event_ids=list(range(2, 60)),
        summary='session fallback summary',
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
            pipeline,
            '_llm_structured_compaction',
            new=AsyncMock(return_value=None),
        ) as mock_llm,
        patch.object(
            pipeline,
            '_session_memory_compaction',
            return_value=session_action,
        ) as mock_session,
        patch.object(pipeline, '_action_meets_effectiveness', return_value=True),
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=True,
        ),
    ):
        action = await pipeline._run_compaction(
            state,
            events,
            events,
            budget,  # type: ignore[arg-type]
            llm_config=SimpleNamespace(model='test-model'),
            force=False,
            critical=False,
        )

    assert action is session_action
    mock_llm.assert_awaited_once()
    mock_session.assert_called_once()


def test_build_prompt_events_injects_context_packet(pipeline):
    events = [_user('implement feature X', 1)]
    state = _make_state(events)

    prompt_events = pipeline.build_prompt_events(events, state=state, llm_config=None)

    from backend.ledger.observation.agent import AgentCondensationObservation

    packet = prompt_events[0]
    assert isinstance(packet, AgentCondensationObservation)
    assert packet.is_working_set is True
    assert '<CONTEXT_PACKET>' in packet.content
    assert 'implement feature X' in packet.content


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
    assert 'Build a raft kv store' in packet.content


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
    assert pipeline._should_skip_compaction(state, force=False) is True

    # Still blocked before threshold.
    state.history.append(_cmd_output('mid', skip_until - 1))
    assert pipeline._should_skip_compaction(state, force=False) is True

    # Unblocked once latest id reaches skip_until (and time backoff expired).
    state.history.append(_cmd_output('past threshold', skip_until))
    pipe = state.extra_data['context_pipeline_state']
    pipe['ineffective_compact_until'] = 0
    state.extra_data['context_pipeline_state'] = pipe
    assert pipeline._should_skip_compaction(state, force=False) is False


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
        'backend.context.context_pipeline._projected_compaction_token_reduction',
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
    pipeline._record_boundary_compact(state, events, action)
    pipe = state.extra_data['context_pipeline_state']
    assert 'skip_compaction_until_event_id' not in pipe
    assert 'ineffective_compact_streak' not in pipe
    assert 'ineffective_compact_until' not in pipe
    assert 'last_boundary_compact_at' in pipe
