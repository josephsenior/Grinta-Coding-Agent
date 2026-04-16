"""Tests for backend.orchestration.tool_pipeline — pipeline dataclasses + middleware."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestration.tool_pipeline import (
    CircuitBreakerMiddleware,
    LoggingMiddleware,
    ToolInvocationContext,
    ToolInvocationMiddleware,
    ToolInvocationPipeline,
)

# ── ToolInvocationContext ─────────────────────────────────────────────


class TestToolInvocationContextPipeline:
    def test_defaults(self):
        ctx = ToolInvocationContext(
            controller=MagicMock(),
            action=MagicMock(),
            state=MagicMock(),
        )
        assert ctx.blocked is False
        assert ctx.block_reason is None
        assert ctx.metadata == {}
        assert ctx.action_id is None

    def test_block_marks_blocked(self):
        ctx = ToolInvocationContext(
            controller=MagicMock(), action=MagicMock(), state=MagicMock()
        )
        ctx.block('safety check')
        assert ctx.blocked is True
        assert ctx.block_reason == 'safety check'

    def test_block_without_reason(self):
        ctx = ToolInvocationContext(
            controller=MagicMock(), action=MagicMock(), state=MagicMock()
        )
        ctx.block()
        assert ctx.blocked is True
        assert ctx.block_reason is None


# ── ToolInvocationMiddleware base ─────────────────────────────────────


class TestToolInvocationMiddlewareBase:
    def test_default_execute_is_noop(self) -> None:
        mw = ToolInvocationMiddleware()
        result = asyncio.run(mw.execute(MagicMock()))
        assert result is None

    def test_default_observe_is_noop(self) -> None:
        mw = ToolInvocationMiddleware()
        result = asyncio.run(mw.observe(MagicMock(), None))
        assert result is None


# ── ToolInvocationPipeline ────────────────────────────────────────────


class TestToolInvocationPipelineCore:
    def test_create_context(self):
        controller = MagicMock()
        pipeline = ToolInvocationPipeline(controller, [])
        action = MagicMock()
        state = MagicMock()
        ctx = pipeline.create_context(action, state)
        assert ctx.controller is controller
        assert ctx.action is action
        assert ctx.state is state
        assert ctx.blocked is False

    @pytest.mark.asyncio
    async def test_run_execute_skips_when_blocked(self):
        mw = MagicMock(spec=ToolInvocationMiddleware)
        mw.execute = AsyncMock()
        pipeline = ToolInvocationPipeline(MagicMock(), [mw])
        ctx = ToolInvocationContext(
            controller=MagicMock(), action=MagicMock(), state=MagicMock()
        )
        ctx.blocked = True
        await pipeline.run_execute(ctx)
        mw.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_observe_passes_observation(self):
        mw = MagicMock(spec=ToolInvocationMiddleware)
        mw.observe = AsyncMock()
        pipeline = ToolInvocationPipeline(MagicMock(), [mw])
        ctx = ToolInvocationContext(
            controller=MagicMock(), action=MagicMock(), state=MagicMock()
        )
        obs = MagicMock()
        await pipeline.run_observe(ctx, obs)
        mw.observe.assert_called_once_with(ctx, observation=obs)
        assert ctx.metadata['observation'] is obs

    @pytest.mark.asyncio
    async def test_middleware_blocking_stops_chain(self):
        mw1 = MagicMock(spec=ToolInvocationMiddleware)

        async def block(ctx):
            ctx.block('mw1 blocked')

        mw1.execute = block

        mw2 = MagicMock(spec=ToolInvocationMiddleware)
        mw2.execute = AsyncMock()

        pipeline = ToolInvocationPipeline(MagicMock(), [mw1, mw2])
        ctx = ToolInvocationContext(
            controller=MagicMock(), action=MagicMock(), state=MagicMock()
        )
        await pipeline.run_execute(ctx)
        assert ctx.blocked is True
        mw2.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_middlewares_run_in_order(self):
        order = []

        mw1 = MagicMock(spec=ToolInvocationMiddleware)

        async def execute1(ctx):
            order.append(1)

        mw1.execute = execute1

        mw2 = MagicMock(spec=ToolInvocationMiddleware)

        async def execute2(ctx):
            order.append(2)

        mw2.execute = execute2

        pipeline = ToolInvocationPipeline(MagicMock(), [mw1, mw2])
        ctx = ToolInvocationContext(
            controller=MagicMock(), action=MagicMock(), state=MagicMock()
        )
        await pipeline.run_execute(ctx)
        assert order == [1, 2]


# ── CircuitBreakerMiddleware ──────────────────────────────────────────


class TestCircuitBreakerMiddlewarePipeline:
    @pytest.mark.asyncio
    async def test_execute_records_high_risk_via_service(self):
        controller = MagicMock()
        service = MagicMock()
        controller.circuit_breaker_service = service
        mw = CircuitBreakerMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller,
            action=MagicMock(security_risk='HIGH'),
            state=MagicMock(),
        )
        await mw.execute(ctx)
        service.record_high_risk_action.assert_called_once_with('HIGH')

    @pytest.mark.asyncio
    async def test_observe_records_success_for_non_error(self):
        controller = MagicMock()
        service = MagicMock()
        controller.circuit_breaker_service = service
        mw = CircuitBreakerMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller, action=MagicMock(), state=MagicMock()
        )
        await mw.observe(ctx, MagicMock())
        service.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_observe_records_error_for_error_obs(self):
        from backend.ledger.observation import ErrorObservation

        controller = MagicMock()
        service = MagicMock()
        controller.circuit_breaker_service = service
        mw = CircuitBreakerMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller, action=MagicMock(), state=MagicMock()
        )
        obs = ErrorObservation(content='something broke')
        await mw.observe(ctx, obs)
        service.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_observe_str_replace_syntax_uses_syntax_bucket(self):
        from backend.ledger.observation import ErrorObservation

        from backend.orchestration.agent_circuit_breaker import (
            STR_REPLACE_EDITOR_SYNTAX_TOOL_NAME,
            STR_REPLACE_EDITOR_TOOL_NAME,
        )

        controller = MagicMock()
        service = MagicMock()
        controller.circuit_breaker_service = service
        mw = CircuitBreakerMiddleware(controller)
        action = MagicMock()
        action.tool_call_metadata = MagicMock(function_name=STR_REPLACE_EDITOR_TOOL_NAME)
        ctx = ToolInvocationContext(
            controller=controller, action=action, state=MagicMock()
        )
        obs = ErrorObservation(content='ERROR:\nSyntax validation failed: bad')
        await mw.observe(ctx, obs)
        service.record_error.assert_called_once()
        assert (
            service.record_error.call_args.kwargs['tool_name']
            == STR_REPLACE_EDITOR_SYNTAX_TOOL_NAME
        )

    @pytest.mark.asyncio
    async def test_observe_str_replace_non_syntax_uses_hard_bucket(self):
        from backend.ledger.observation import ErrorObservation

        from backend.orchestration.agent_circuit_breaker import (
            STR_REPLACE_EDITOR_TOOL_NAME,
        )

        controller = MagicMock()
        service = MagicMock()
        controller.circuit_breaker_service = service
        mw = CircuitBreakerMiddleware(controller)
        action = MagicMock()
        action.tool_call_metadata = MagicMock(function_name=STR_REPLACE_EDITOR_TOOL_NAME)
        ctx = ToolInvocationContext(
            controller=controller, action=action, state=MagicMock()
        )
        obs = ErrorObservation(content='old_str not found')
        await mw.observe(ctx, obs)
        assert (
            service.record_error.call_args.kwargs['tool_name']
            == STR_REPLACE_EDITOR_TOOL_NAME
        )

    @pytest.mark.asyncio
    async def test_observe_none_observation_is_noop(self):
        controller = MagicMock()
        service = MagicMock()
        controller.circuit_breaker_service = service
        mw = CircuitBreakerMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller, action=MagicMock(), state=MagicMock()
        )
        await mw.observe(ctx, None)
        service.record_error.assert_not_called()
        service.record_success.assert_not_called()


# ── LoggingMiddleware ─────────────────────────────────────────────────


class TestLoggingMiddlewarePipeline:
    @pytest.mark.asyncio
    async def test_execute_logs(self):
        controller = MagicMock()
        mw = LoggingMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller, action=MagicMock(), state=MagicMock()
        )
        await mw.execute(ctx)
        controller.log.assert_called_once()
        assert 'EXECUTE' in controller.log.call_args[0][1]

    @pytest.mark.asyncio
    async def test_observe_none_is_noop(self):
        controller = MagicMock()
        mw = LoggingMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller, action=MagicMock(), state=MagicMock()
        )
        await mw.observe(ctx, None)
        controller.log.assert_not_called()

    @pytest.mark.asyncio
    async def test_observe_with_observation_logs(self):
        controller = MagicMock()
        mw = LoggingMiddleware(controller)
        ctx = ToolInvocationContext(
            controller=controller, action=MagicMock(), state=MagicMock()
        )
        await mw.observe(ctx, MagicMock())
        controller.log.assert_called_once()
        assert 'OBSERVE' in controller.log.call_args[0][1]
