"""Tests for backend.orchestration.services.observation_service."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.orchestration.services.observation_service import (
    ObservationService,
    transition_agent_state_logic,
)
from backend.orchestration.state.state import AgentState


def _make_context() -> MagicMock:
    controller = MagicMock()
    controller.state = MagicMock()
    controller.state.agent_state = AgentState.RUNNING
    controller.agent = MagicMock()
    controller.agent.llm.config.max_message_chars = 5000
    controller.set_agent_state_to = AsyncMock()
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    ctx.pop_action_context.return_value = None
    return ctx


def _make_pending_service(action=None) -> MagicMock:
    svc = MagicMock()
    svc.get.return_value = action
    action_id = getattr(action, 'id', None) if action else None

    def _peek_for_cause(cause):
        if action is None:
            return None
        if cause is None:
            return None
        try:
            if int(cause) == action_id:
                return action
        except (TypeError, ValueError):
            pass
        return None

    svc.peek_for_cause.side_effect = _peek_for_cause
    svc.pop_for_cause.return_value = action
    svc.has_outstanding_for_cause.side_effect = (
        lambda cause: cause is not None
        and action_id is not None
        and int(cause) == action_id
    )
    svc.set = MagicMock()
    return svc


def _make_observation(content: str = 'result', cause: int | None = None) -> Any:
    return cast(Any, SimpleNamespace(content=content, cause=cause))


# ── transition_agent_state_logic ─────────────────────────────────────


class TestTransitionLogic:
    @pytest.mark.asyncio
    async def test_user_confirmed_transitions_to_running(self):
        controller = MagicMock()
        controller.state.agent_state = AgentState.USER_CONFIRMED
        controller.set_agent_state_to = AsyncMock()
        controller.tool_pipeline = None
        obs = _make_observation()
        await transition_agent_state_logic(controller, None, obs)
        controller.set_agent_state_to.assert_called_once_with(AgentState.RUNNING)

    @pytest.mark.asyncio
    async def test_user_rejected_transitions_to_awaiting_input(self):
        controller = MagicMock()
        controller.state.agent_state = AgentState.USER_REJECTED
        controller.set_agent_state_to = AsyncMock()
        controller.tool_pipeline = None
        obs = _make_observation()
        await transition_agent_state_logic(controller, None, obs)
        controller.set_agent_state_to.assert_called_once_with(
            AgentState.AWAITING_USER_INPUT
        )

    @pytest.mark.asyncio
    async def test_runs_pipeline_observe_when_ctx_present(self):
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING
        pipeline = AsyncMock()
        controller.tool_pipeline = pipeline
        ctx = MagicMock()
        obs = _make_observation()
        await transition_agent_state_logic(controller, ctx, obs)
        pipeline.run_observe.assert_called_once_with(ctx, obs)
        controller._cleanup_action_context.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_no_pipeline_skips(self):
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING
        controller.tool_pipeline = None
        ctx = MagicMock()
        obs = _make_observation()
        await transition_agent_state_logic(controller, ctx, obs)
        # no error, no crash


# ── ObservationService._get_log_level ────────────────────────────────


class TestGetLogLevel:
    def test_debug_by_default(self):
        ctx = _make_context()
        svc = ObservationService(ctx, _make_pending_service())
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('LOG_ALL_EVENTS', None)
            assert svc._get_log_level() == 'debug'

    def test_info_when_log_all_events_true(self):
        ctx = _make_context()
        svc = ObservationService(ctx, _make_pending_service())
        with patch.dict(os.environ, {'LOG_ALL_EVENTS': 'true'}):
            assert svc._get_log_level() == 'info'

    def test_info_when_log_all_events_1(self):
        ctx = _make_context()
        svc = ObservationService(ctx, _make_pending_service())
        with patch.dict(os.environ, {'LOG_ALL_EVENTS': '1'}):
            assert svc._get_log_level() == 'info'


# ── ObservationService._prepare_observation_for_logging ──────────────


class TestPrepareObservation:
    def test_truncates_long_content(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        controller.agent.llm.config.max_message_chars = 10
        svc = ObservationService(ctx, _make_pending_service())
        obs = _make_observation(content='A' * 100)
        result = svc._prepare_observation_for_logging(obs)
        assert len(result.content) <= 100  # truncated from original

    def test_short_content_unchanged(self):
        ctx = _make_context()
        svc = ObservationService(ctx, _make_pending_service())
        obs = _make_observation(content='short')
        result = svc._prepare_observation_for_logging(obs)
        assert result.content == 'short'


# ── ObservationService.handle_observation ────────────────────────────


class TestHandleObservation:
    @pytest.mark.asyncio
    async def test_logs_observation(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        pending_svc = _make_pending_service(action=None)
        svc = ObservationService(ctx, pending_svc)
        obs = _make_observation(content='hello')
        await svc.handle_observation(obs)
        controller.log.assert_called()

    @pytest.mark.asyncio
    async def test_matching_pending_action_clears(self):
        ctx = _make_context()
        controller = ctx.get_controller()
        controller.state.agent_state = AgentState.RUNNING
        controller.confirmation_service = None
        pending_action = SimpleNamespace(id=42)
        pending_svc = _make_pending_service(action=pending_action)
        svc = ObservationService(ctx, pending_svc)
        obs = _make_observation(content='done', cause=42)
        with patch('backend.core.plugin.get_plugin_registry') as mock_reg:
            mock_reg.return_value.dispatch_action_post = AsyncMock(return_value=obs)
            await svc.handle_observation(obs)
        pending_svc.pop_for_cause.assert_called_with(42)

    @pytest.mark.asyncio
    async def test_non_matching_cause_drops_silently(self):
        ctx = _make_context()
        pending_action = SimpleNamespace(id=42)
        pending_svc = _make_pending_service(action=pending_action)
        svc = ObservationService(ctx, pending_svc)
        obs = _make_observation(content='other', cause=99)  # different cause
        await svc.handle_observation(obs)
        # cause=99 is int-like but has no outstanding entry → dropped silently
        pending_svc.set.assert_not_called()
