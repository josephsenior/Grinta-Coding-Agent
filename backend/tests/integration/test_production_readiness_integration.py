"""Integration tests for long-session compaction, provider recovery, and MCP edges."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compact_boundary import project_after_compact_boundary
from backend.context.context_pipeline import ContextPipeline
from backend.core.config.compactor_config import ContextPipelineConfig
from backend.inference.exceptions import AuthenticationError, RateLimitError
from backend.integrations.mcp.mcp_utils import call_tool_mcp
from backend.ledger.action.agent import CondensationAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation
from backend.orchestration.services.recovery_service import (
    _HARD_STOP_EXCEPTIONS,
    _QUEUED_RETRY_EXCEPTIONS,
)


def _user(text: str, event_id: int) -> MessageAction:
    action = MessageAction(content=text)
    action.id = event_id
    action.source = EventSource.USER
    return action


def _build_long_session_events(count: int = 240) -> list:
    events: list = [_user('stabilize failing integration tests', 1)]
    for i in range(2, count + 1):
        obs = CmdOutputObservation(
            content=f'integration log chunk {i}\n' * 40,
            command=f'pytest -k case_{i}',
            metadata={},
        )
        obs.id = i
        events.append(obs)
    return events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_long_session_compaction_preserves_recent_boundary(tmp_path) -> None:
    events = _build_long_session_events(240)
    state = MagicMock()
    state.history = events
    state.extra_data = {}
    state.view = MagicMock(unhandled_condensation_request=False)
    state.turn_signals = MagicMock(memory_pressure='high', prewarmed_compaction=None)
    state.ack_memory_pressure = MagicMock()
    state.agent = None
    state.session_id = 'integration-long-session'
    state.iteration_flag = None
    state.set_extra = lambda key, value, source='test': state.extra_data.__setitem__(
        key, value
    )

    pipeline = ContextPipeline(
        llm_registry=MagicMock(),
        config=ContextPipelineConfig(),
    )
    llm_action = CondensationAction(
        pruned_event_ids=list(range(2, 202)),
        summary='Long-session compaction summary ' * 20,
        summary_offset=0,
    )
    llm_config = SimpleNamespace(
        max_input_tokens=24_000,
        model='integration-model',
        prompt_history_windowing_enabled=True,
        prompt_history_token_budget=12_000,
    )

    monkeypatch_paths = (
        'backend.context.compactor.pre_condensation_snapshot._snapshot_path',
        'backend.context.compactor.pre_condensation_snapshot._snapshot_staging_path',
        'backend.context.memory.session_memory._session_memory_path',
    )
    with (
        patch(monkeypatch_paths[0], lambda state=None: tmp_path / 'snapshot.json'),
        patch(monkeypatch_paths[1], lambda state=None: tmp_path / 'snapshot.staging.json'),
        patch(monkeypatch_paths[2], lambda state=None: tmp_path / 'session_memory.md'),
        patch('backend.context.context_pipeline.finalize_compaction_artifacts'),
        patch('backend.context.context_pipeline.delete_staging_snapshot'),
        patch('backend.context.context_pipeline.maybe_update'),
        patch(
            'backend.context.context_pipeline.session_memory_exists',
            return_value=False,
        ),
        patch.object(pipeline, '_llm_config', return_value=llm_config),
        patch.object(
            pipeline._compaction_engine,
            'run',
            new=AsyncMock(return_value=llm_action),
        ),
    ):
        condensed = await pipeline.prepare_step(state)

    assert condensed.pending_action is not None
    action = condensed.pending_action
    assert isinstance(action, CondensationAction)
    projected = project_after_compact_boundary([*events, action])
    assert len(projected) < len(events)
    assert len(projected) >= 10


@pytest.mark.integration
def test_provider_auth_failure_is_hard_stop() -> None:
    assert isinstance(AuthenticationError('bad key'), _HARD_STOP_EXCEPTIONS)


@pytest.mark.integration
def test_provider_rate_limit_uses_retry_queue() -> None:
    assert isinstance(RateLimitError('provider throttled'), _QUEUED_RETRY_EXCEPTIONS)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_connection_reset_is_retryable_envelope() -> None:
    action = MCPAction(name='search-web', arguments={'queries': ['retry me']})

    client = AsyncMock()
    client.tools = [SimpleNamespace(name='search-web')]
    client.exposed_to_protocol = {}
    client.call_tool = AsyncMock(side_effect=ConnectionResetError('connection reset'))

    obs = await call_tool_mcp([client], action)
    payload = __import__('json').loads(obs.content)
    assert payload['ok'] is False
    assert payload['retryable'] is True
    assert payload['error_code'] == 'MCP_SERVER_UNAVAILABLE'
