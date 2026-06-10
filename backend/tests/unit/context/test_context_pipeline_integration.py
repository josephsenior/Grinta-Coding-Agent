"""Integration-style test for unified context pipeline long sessions.

Manual 45+ minute session replay checklist (workspace ``New folder (4)``):
- CONDENSATION actions total < 20 (not hundreds of micro-prunes)
- No burst of degraded boundary (5c) every few seconds
- LLM calls completed grows steadily in the second half
- No ON_EVENT_EXCEPTION at session start
- No retry-queue worker warning after RUNNING
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.context.compact_boundary import project_after_compact_boundary
from backend.context.context_pipeline import ContextPipeline
from backend.context.tool_result_storage import extract_latest_pytest_summary
from backend.core.config.compactor_config import ContextPipelineConfig
from backend.ledger.action.agent import CondensationAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation


def _user(text: str, event_id: int) -> MessageAction:
    action = MessageAction(content=text)
    action.id = event_id
    action.source = EventSource.USER
    return action


def _pytest_obs(event_id: int, *, failed: int = 2, passed: int = 10) -> CmdOutputObservation:
    content = (
        f'============================= test session starts ==============================\n'
        f'collected 12 items\n\n'
        f'======================== {failed} failed, {passed} passed in 1.23s ========================\n'
    )
    obs = CmdOutputObservation(content=content, command='pytest -q', metadata={})
    obs.id = event_id
    return obs


def _build_pytest_session_events(count: int = 600) -> list:
    events: list = [_user('fix failing pytest tests in backend/', 1)]
    for i in range(2, count + 1):
        if i % 50 == 0:
            events.append(_pytest_obs(i))
        else:
            text = f'log chunk {i}\n' * 80
            obs = CmdOutputObservation(content=text, command=f'pytest -k test_{i}', metadata={})
            obs.id = i
            events.append(obs)
    return events


def _make_state(events: list) -> MagicMock:
    state = MagicMock()
    state.history = events
    state.extra_data = {}
    state.view = MagicMock(unhandled_condensation_request=False)
    state.turn_signals = MagicMock(memory_pressure=None, prewarmed_compaction=None)
    state.ack_memory_pressure = MagicMock()
    state.agent = None
    state.session_id = 'integration-session'
    state.iteration_flag = None

    def _set_extra(key, value, source='test'):
        state.extra_data[key] = value

    state.set_extra = _set_extra
    return state


@pytest.mark.asyncio
async def test_six_hundred_event_pytest_session_commits_boundary_and_preserves_pytest(
    tmp_path, monkeypatch,
):
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
    events = _build_pytest_session_events(600)
    state = _make_state(events)
    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(allow_llm_hot_path=False),
    )
    llm_config = SimpleNamespace(
        max_input_tokens=32_000,
        model='test-model',
        prompt_history_windowing_enabled=True,
        prompt_history_token_budget=16_000,
    )

    with (
        patch('backend.context.context_pipeline.commit_snapshot'),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch('backend.context.context_pipeline.sync_snapshot_to_working_memory'),
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=False,
        ),
        patch.object(pipeline, '_llm_config', return_value=llm_config),
    ):
        condensed = await pipeline.prepare_step(state)

    assert condensed.pending_action is not None
    action = condensed.pending_action
    assert isinstance(action, CondensationAction)
    assert action.summary
    assert len(action.pruned) >= 20

    synthetic_history = [*events, action]
    projected = project_after_compact_boundary(synthetic_history)
    assert len(projected) < 200
    assert len(projected) >= 15

    prompt_events = pipeline.build_prompt_events(
        [],
        state=state,
        llm_config=llm_config,
        full_history=synthetic_history,
    )
    assert len(prompt_events) >= 15
    assert extract_latest_pytest_summary(synthetic_history) is not None

    from backend.context.pre_condensation_snapshot import delete_snapshot

    delete_snapshot()
