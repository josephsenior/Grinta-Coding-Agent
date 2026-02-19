"""Tests for backend.controller.services.iteration_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.controller.services.iteration_service import IterationService


# ── helpers ──────────────────────────────────────────────────────────


def _make_service(**ctx_overrides):
    ctx = MagicMock()
    agent = MagicMock()
    config = SimpleNamespace(
        enable_dynamic_iterations=True,
        min_iterations=20,
        max_iterations_override=500,
        complexity_iteration_multiplier=50.0,
    )
    state = MagicMock()
    iteration_flag = MagicMock()
    iteration_flag.max_value = 100
    state.iteration_flag = iteration_flag
    state.adjust_iteration_limit = MagicMock()

    ctx.agent = agent
    ctx.agent_config = config
    ctx.state = state
    for k, v in ctx_overrides.items():
        setattr(ctx, k, v)
    svc = IterationService(ctx)
    return svc, ctx, config, state, iteration_flag


# ── _should_apply_iterations ─────────────────────────────────────────


class TestShouldApply:
    def test_enabled(self):
        svc, ctx, *_ = _make_service()
        assert svc._should_apply_iterations(ctx.agent, ctx.agent_config, ctx.state)

    def test_disabled(self):
        svc, ctx, config, *_ = _make_service()
        config.enable_dynamic_iterations = False
        assert not svc._should_apply_iterations(ctx.agent, config, ctx.state)

    def test_none_agent(self):
        svc, ctx, *_ = _make_service()
        assert not svc._should_apply_iterations(None, ctx.agent_config, ctx.state)


# ── _fallback_iteration_target ───────────────────────────────────────


class TestFallbackTarget:
    def test_basic(self):
        svc, _, config, *_ = _make_service()
        target = svc._fallback_iteration_target(config, 5.0)
        # 20 + 5.0 * 50.0 = 270
        assert target == 270


# ── _apply_iteration_flag ────────────────────────────────────────────


class TestApplyIterationFlag:
    def test_sets_max_via_state(self):
        svc, ctx, config, state, iflag = _make_service()
        svc._apply_iteration_flag(iflag, config, 5.0, 270)
        state.adjust_iteration_limit.assert_called_once_with(
            270, source="IterationService"
        )

    def test_respects_max_override(self):
        svc, ctx, config, state, iflag = _make_service()
        config.max_iterations_override = 100
        svc._apply_iteration_flag(iflag, config, 5.0, 270)
        # Should be capped at 100
        state.adjust_iteration_limit.assert_called_once()
        call_arg = state.adjust_iteration_limit.call_args[0][0]
        assert call_arg <= 100


# ── apply_dynamic_iterations ─────────────────────────────────────────


class TestApplyDynamic:
    @pytest.mark.asyncio
    async def test_no_complexity_skips(self):
        svc, ctx, *_ = _make_service()
        tool_ctx = MagicMock()
        tool_ctx.metadata = {}
        await svc.apply_dynamic_iterations(tool_ctx)
        # Should not crash and not adjust

    @pytest.mark.asyncio
    async def test_disabled_skips(self):
        svc, ctx, config, state, iflag = _make_service()
        config.enable_dynamic_iterations = False
        tool_ctx = MagicMock()
        tool_ctx.metadata = {"task_complexity": 5.0}
        await svc.apply_dynamic_iterations(tool_ctx)
        state.adjust_iteration_limit.assert_not_called()

    @pytest.mark.asyncio
    async def test_adjusts_with_complexity(self):
        svc, ctx, config, state, iflag = _make_service()
        tool_ctx = MagicMock()
        tool_ctx.metadata = {"task_complexity": 3.0}
        ctx.agent.task_complexity_analyzer = None  # use fallback
        await svc.apply_dynamic_iterations(tool_ctx)
        state.adjust_iteration_limit.assert_called_once()
