"""Tests for backend.context.context_pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.context_pipeline import ContextPipeline
from backend.core.config.compactor_config import ContextPipelineConfig
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
        lambda: tmp_path / 'pre_condensation_snapshot.json',
    )
    monkeypatch.setattr(
        'backend.context.pre_condensation_snapshot._snapshot_staging_path',
        lambda: tmp_path / '.pre_condensation_snapshot.staging.json',
    )
    monkeypatch.setattr(
        'backend.context.session_memory._session_memory_path',
        lambda: tmp_path / 'session_memory.md',
    )


@pytest.mark.asyncio
async def test_prepare_step_skips_compaction_under_threshold(pipeline):
    events = [_user('fix tests', 1), _cmd_output('ok', 2)]
    state = _make_state(events)
    with patch('backend.context.context_pipeline.ContextBudget') as mock_budget:
        mock_budget.from_events.return_value = SimpleNamespace(should_autocompact=False)
        result = await pipeline.prepare_step(state)
    assert result.pending_action is None
    assert result.events == events


@pytest.mark.asyncio
async def test_prepare_step_commits_degraded_boundary_when_over_threshold(pipeline):
    events = [_user('run pytest', 1)]
    for i in range(2, 402):
        events.append(_cmd_output(f'output line {i}\n' * 20, i))
    state = _make_state(events)
    with (
        patch('backend.context.context_pipeline.ContextBudget') as mock_budget,
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=False,
        ),
        patch(
            'backend.context.context_pipeline.build_compaction_summary',
            return_value='# Session Memory\npytest failing',
        ),
        patch('backend.context.context_pipeline.commit_snapshot'),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch('backend.context.context_pipeline.sync_snapshot_to_working_memory'),
    ):
        mock_budget.from_events.return_value = SimpleNamespace(should_autocompact=True)
        result = await pipeline.prepare_step(state)
    assert result.pending_action is not None
    assert isinstance(result.pending_action, CondensationAction)
    assert result.pending_action.summary
    assert len(result.pending_action.pruned) > 0
    assert result.events == []


@pytest.mark.asyncio
async def test_prepare_step_uses_prewarmed_compaction(pipeline):
    action = CondensationAction(
        pruned_event_ids=[1, 2],
        summary='prewarmed',
        summary_offset=0,
    )
    prewarmed = Compaction(action=action)
    state = _make_state([_user('hello', 1)])
    state.turn_signals.prewarmed_compaction = prewarmed
    with (
        patch('backend.context.context_pipeline.commit_snapshot'),
        patch('backend.context.context_pipeline.sync_snapshot_to_working_memory'),
    ):
        result = await pipeline.prepare_step(state)
    assert result.pending_action is action
    assert result.events == []


def test_build_prompt_events_injects_working_set(pipeline):
    events = [_user('implement feature X', 1)]
    state = _make_state(events)
    with patch(
        'backend.context.context_pipeline.build_working_set_observation',
        return_value=MagicMock(id=99),
    ):
        prompt_events = pipeline.build_prompt_events(events, state=state, llm_config=None)
    assert len(prompt_events) >= 1
