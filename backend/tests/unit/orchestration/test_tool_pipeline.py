"""Unit tests for backend.orchestration.tool_pipeline — Middleware pipeline."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.orchestration.tool_pipeline import (
    ToolInvocationContext,
    ToolInvocationMiddleware,
    ToolInvocationPipeline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_controller():
    ctrl = MagicMock()
    ctrl.id = 'test-session'
    ctrl.state = MagicMock()
    ctrl.state.iteration_flag = MagicMock(current_value=1)
    ctrl.state.history = []
    ctrl.log = MagicMock()
    ctrl.event_stream = MagicMock()
    ctrl._pending_action = None
    return ctrl


def _mock_action(runnable=True):
    action = MagicMock()
    action.runnable = runnable
    action.action = 'run'
    action.command = 'echo hello'
    return action


def _mock_state():
    state = MagicMock()
    state.iteration_flag = MagicMock(current_value=1)
    state.history = []
    return state


# ---------------------------------------------------------------------------
# ToolInvocationContext
# ---------------------------------------------------------------------------


class TestToolInvocationContext:
    def test_default_fields(self):
        ctrl = _mock_controller()
        action = _mock_action()
        state = _mock_state()
        ctx = ToolInvocationContext(controller=ctrl, action=action, state=state)
        assert ctx.blocked is False
        assert ctx.block_reason is None
        assert ctx.metadata == {}
        assert ctx.action_id is None

    def test_block_method(self):
        ctx = ToolInvocationContext(
            controller=_mock_controller(),
            action=_mock_action(),
            state=_mock_state(),
        )
        ctx.block('test reason')
        assert ctx.blocked is True
        assert ctx.block_reason == 'test reason'

    def test_block_without_reason(self):
        ctx = ToolInvocationContext(
            controller=_mock_controller(),
            action=_mock_action(),
            state=_mock_state(),
        )
        ctx.block()
        assert ctx.blocked is True
        assert ctx.block_reason is None

    def test_metadata_storage(self):
        ctx = ToolInvocationContext(
            controller=_mock_controller(),
            action=_mock_action(),
            state=_mock_state(),
            metadata={'key': 'value'},
        )
        assert ctx.metadata['key'] == 'value'


# ---------------------------------------------------------------------------
# ToolInvocationMiddleware — base class no-ops
# ---------------------------------------------------------------------------


class TestBaseMiddleware:
    def test_execute_is_noop(self) -> None:
        mw = ToolInvocationMiddleware()
        ctx = ToolInvocationContext(
            controller=_mock_controller(),
            action=_mock_action(),
            state=_mock_state(),
        )
        result = asyncio.run(mw.execute(ctx))
        assert result is None

    def test_observe_is_noop(self) -> None:
        mw = ToolInvocationMiddleware()
        ctx = ToolInvocationContext(
            controller=_mock_controller(),
            action=_mock_action(),
            state=_mock_state(),
        )
        result = asyncio.run(mw.observe(ctx, None))
        assert result is None


# ---------------------------------------------------------------------------
# ToolInvocationPipeline — stage execution
# ---------------------------------------------------------------------------


class _RecordingMiddleware(ToolInvocationMiddleware):
    """Records which stages were called."""

    def __init__(self):
        self.calls = []

    async def execute(self, ctx):
        self.calls.append('execute')

    async def observe(self, ctx, observation=None):
        self.calls.append('observe')


class _BlockingMiddleware(ToolInvocationMiddleware):
    """Blocks execution during execute stage."""

    async def execute(self, ctx):
        ctx.block('blocked by test')


class TestPipelineStageExecution:
    @pytest.mark.asyncio
    async def test_run_execute_calls_execute(self):
        ctrl = _mock_controller()
        mw = _RecordingMiddleware()
        pip = ToolInvocationPipeline(ctrl, [mw])
        ctx = pip.create_context(_mock_action(), _mock_state())
        await pip.run_execute(ctx)
        assert 'execute' in mw.calls

    @pytest.mark.asyncio
    async def test_run_observe_calls_observe(self):
        ctrl = _mock_controller()
        mw = _RecordingMiddleware()
        pip = ToolInvocationPipeline(ctrl, [mw])
        ctx = pip.create_context(_mock_action(), _mock_state())
        await pip.run_observe(ctx, None)
        assert 'observe' in mw.calls

    @pytest.mark.asyncio
    async def test_observe_stores_observation_in_metadata(self):
        ctrl = _mock_controller()
        mw = _RecordingMiddleware()
        pip = ToolInvocationPipeline(ctrl, [mw])
        ctx = pip.create_context(_mock_action(), _mock_state())
        obs = MagicMock()
        await pip.run_observe(ctx, obs)
        assert ctx.metadata['observation'] is obs


# ---------------------------------------------------------------------------
# Blocking propagation
# ---------------------------------------------------------------------------


class TestBlockingPropagation:
    @pytest.mark.asyncio
    async def test_blocked_context_skips_execute(self):
        ctrl = _mock_controller()
        mw = _RecordingMiddleware()
        pip = ToolInvocationPipeline(ctrl, [mw])
        ctx = pip.create_context(_mock_action(), _mock_state())
        ctx.blocked = True
        await pip.run_execute(ctx)
        assert 'execute' not in mw.calls

    @pytest.mark.asyncio
    async def test_blocking_middleware_stops_subsequent(self):
        ctrl = _mock_controller()
        blocker = _BlockingMiddleware()
        recorder = _RecordingMiddleware()
        pip = ToolInvocationPipeline(ctrl, [blocker, recorder])
        ctx = pip.create_context(_mock_action(), _mock_state())
        await pip.run_execute(ctx)
        assert ctx.blocked is True
        assert ctx.block_reason == 'blocked by test'
        assert 'execute' not in recorder.calls


# ---------------------------------------------------------------------------
# Multiple middlewares — ordering
# ---------------------------------------------------------------------------


class TestMiddlewareOrdering:
    @pytest.mark.asyncio
    async def test_middlewares_execute_in_order(self):
        ctrl = _mock_controller()
        order = []

        class MW1(ToolInvocationMiddleware):
            async def execute(self, ctx):
                order.append(1)

        class MW2(ToolInvocationMiddleware):
            async def execute(self, ctx):
                order.append(2)

        class MW3(ToolInvocationMiddleware):
            async def execute(self, ctx):
                order.append(3)

        pip = ToolInvocationPipeline(ctrl, [MW1(), MW2(), MW3()])
        ctx = pip.create_context(_mock_action(), _mock_state())
        await pip.run_execute(ctx)
        assert order == [1, 2, 3]


# ---------------------------------------------------------------------------
# Error handling in middleware
# ---------------------------------------------------------------------------


class TestMiddlewareErrorHandling:
    @pytest.mark.asyncio
    async def test_exception_in_middleware_blocks_context(self):
        ctrl = _mock_controller()

        class FailingMiddleware(ToolInvocationMiddleware):
            async def execute(self, ctx):
                raise RuntimeError('boom')

        recorder = _RecordingMiddleware()
        pip = ToolInvocationPipeline(ctrl, [FailingMiddleware(), recorder])
        ctx = pip.create_context(_mock_action(), _mock_state())
        await pip.run_execute(ctx)
        assert ctx.blocked is True
        assert ctx.block_reason is not None
        assert 'execute_error' in ctx.block_reason
        # recorder should NOT have been called
        assert 'execute' not in recorder.calls


# ---------------------------------------------------------------------------
# create_context
# ---------------------------------------------------------------------------


class TestCreateContext:
    def test_creates_context_with_correct_fields(self):
        ctrl = _mock_controller()
        pip = ToolInvocationPipeline(ctrl, [])
        action = _mock_action()
        state = _mock_state()
        ctx = pip.create_context(action, state)
        assert ctx.controller is ctrl
        assert ctx.action is action
        assert ctx.state is state
        assert ctx.blocked is False
        assert ctx.metadata == {}




