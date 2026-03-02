"""Tests for backend.controller.services.action_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from typing import Any, cast

import pytest

from backend.controller.services.action_service import ActionService
from backend.events.action import Action


def _make_context() -> MagicMock:
    controller = MagicMock()
    controller.event_stream = MagicMock()
    controller.tool_pipeline = None
    controller.telemetry_service = MagicMock()
    controller.conversation_stats = MagicMock()
    controller.state = MagicMock()
    controller.state.budget_flag = None
    controller.state.metrics = MagicMock()
    controller.state.metrics.token_usages = []
    controller.state.metrics.accumulated_token_usage = SimpleNamespace(
        prompt_tokens=0, completion_tokens=0
    )
    # Mock get_combined_metrics to return a proper metrics-like object
    controller.conversation_stats.get_combined_metrics.return_value = SimpleNamespace(
        accumulated_cost=0.5,
        accumulated_token_usage=SimpleNamespace(
            prompt_tokens=100, completion_tokens=50
        ),
        max_budget_per_task=10.0,
    )
    controller._bind_action_context = MagicMock()
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    return ctx


def _make_pending_service() -> MagicMock:
    ps = MagicMock()
    ps.set = MagicMock()
    ps.get.return_value = None
    ps.info.return_value = None
    return ps


def _make_confirmation_service() -> MagicMock:
    cs = MagicMock()
    cs.evaluate_action = AsyncMock()
    cs.handle_pending_confirmation = AsyncMock(return_value=False)
    return cs


# ── run: type check ─────────────────────────────────────────────────


class TestRunTypeCheck:
    @pytest.mark.asyncio
    async def test_rejects_non_action(self):
        svc = ActionService(
            _make_context(), _make_pending_service(), _make_confirmation_service()
        )
        with pytest.raises(TypeError, match="requires an Action"):
            await svc.run(cast(Any, "not_an_action"), None)


# ── run: blocked ─────────────────────────────────────────────────────


class TestRunBlocked:
    @pytest.mark.asyncio
    async def test_blocked_ctx_calls_handle_blocked(self):
        ctx_mock = _make_context()
        controller = ctx_mock.get_controller()
        svc = ActionService(
            ctx_mock, _make_pending_service(), _make_confirmation_service()
        )
        action = MagicMock(spec=Action)
        action.runnable = True
        action.source = None
        inv_ctx = MagicMock()
        inv_ctx.blocked = True
        inv_ctx.block_reason = "too risky"
        await svc.run(action, inv_ctx)
        controller.telemetry_service.handle_blocked_invocation.assert_called_once()


# ── set_pending_action / get_pending_action ──────────────────────────


class TestPendingActionDelegation:
    def test_set_delegates(self):
        ps = _make_pending_service()
        svc = ActionService(_make_context(), ps, _make_confirmation_service())
        action = MagicMock(spec=Action)
        svc.set_pending_action(action)
        ps.set.assert_called_once_with(action)

    def test_get_delegates(self):
        ps = _make_pending_service()
        sentinel = MagicMock(spec=Action)
        ps.get.return_value = sentinel
        svc = ActionService(_make_context(), ps, _make_confirmation_service())
        assert svc.get_pending_action() is sentinel

    def test_get_info_delegates(self):
        ps = _make_pending_service()
        info_val = (MagicMock(), 1.0)
        ps.info.return_value = info_val
        svc = ActionService(_make_context(), ps, _make_confirmation_service())
        assert svc.get_pending_action_info() == info_val


# ── _prepare_metrics_for_action ──────────────────────────────────────


class TestPrepareMetrics:
    def test_attaches_metrics_to_action(self):
        ctx_mock = _make_context()
        svc = ActionService(
            ctx_mock, _make_pending_service(), _make_confirmation_service()
        )
        action = MagicMock(spec=Action)
        action.llm_metrics = None
        svc._prepare_metrics_for_action(action)
        assert action.llm_metrics is not None
        assert action.llm_metrics.accumulated_cost == 0.5
