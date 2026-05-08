"""Tests for IdempotencyMiddleware — duplicate action detection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.ledger.action import CmdRunAction
from backend.ledger.observation import NullObservation
from backend.orchestration.middleware.idempotency import IdempotencyMiddleware
from backend.orchestration.tool_pipeline import ToolInvocationContext


@pytest.fixture
def controller():
    ctrl = MagicMock()
    ctrl.event_stream = MagicMock()
    return ctrl


@pytest.fixture
def middleware(controller):
    return IdempotencyMiddleware(controller)


@pytest.fixture
def ctx(controller):
    action = CmdRunAction(command='echo hello')
    return ToolInvocationContext(
        controller=controller,
        action=action,
        state=MagicMock(),
    )


@pytest.mark.asyncio
async def test_non_runnable_action_skipped(middleware, controller) -> None:
    """Non-runnable actions are ignored (not idempotency-checked)."""
    from backend.ledger.action import MessageAction

    action = MessageAction(content='hello')
    assert not action.runnable
    ctx = ToolInvocationContext(
        controller=controller, action=action, state=MagicMock()
    )
    await middleware.execute(ctx)
    assert not ctx.blocked
    assert len(middleware._seen_keys) == 0


@pytest.mark.asyncio
async def test_first_call_not_blocked(middleware, ctx) -> None:
    """First invocation of a unique action passes through."""
    await middleware.execute(ctx)
    assert not ctx.blocked


@pytest.mark.asyncio
async def test_duplicate_call_blocked(middleware, ctx) -> None:
    """Duplicate action invocation is blocked."""
    await middleware.execute(ctx)
    assert not ctx.blocked

    ctx2 = ToolInvocationContext(
        controller=ctx.controller,
        action=CmdRunAction(command='echo hello'),
        state=MagicMock(),
    )
    await middleware.execute(ctx2)
    assert ctx2.blocked
    assert ctx2.block_reason == 'idempotency_duplicate'


@pytest.mark.asyncio
async def test_duplicate_emits_null_observation(middleware, ctx) -> None:
    """Duplicate action emits a NullObservation via the event stream."""
    await middleware.execute(ctx)

    ctx2 = ToolInvocationContext(
        controller=ctx.controller,
        action=CmdRunAction(command='echo hello'),
        state=MagicMock(),
    )
    await middleware.execute(ctx2)

    assert ctx2.controller.event_stream.add_event.called
    call_args = ctx2.controller.event_stream.add_event.call_args[0]
    obs = call_args[0]
    assert isinstance(obs, NullObservation)
    assert '[Duplicate skipped]' in obs.content


@pytest.mark.asyncio
async def test_different_actions_not_blocked(middleware, controller) -> None:
    """Different actions (different idempotency keys) are not blocked."""
    action1 = CmdRunAction(command='echo hello')
    ctx1 = ToolInvocationContext(
        controller=controller, action=action1, state=MagicMock()
    )
    await middleware.execute(ctx1)
    assert not ctx1.blocked

    action2 = CmdRunAction(command='echo world')
    assert action1.idempotency_key != action2.idempotency_key
    ctx2 = ToolInvocationContext(
        controller=controller, action=action2, state=MagicMock()
    )
    await middleware.execute(ctx2)
    assert not ctx2.blocked


@pytest.mark.asyncio
async def test_empty_idempotency_key_skipped(middleware, controller) -> None:
    """Action with empty idempotency_key is not tracked."""
    action = CmdRunAction(command='echo test')
    object.__setattr__(action, 'idempotency_key', '')
    ctx = ToolInvocationContext(
        controller=controller, action=action, state=MagicMock()
    )
    await middleware.execute(ctx)
    assert not ctx.blocked
    assert len(middleware._seen_keys) == 0


@pytest.mark.asyncio
async def test_middleware_clears_pending_action_on_block(middleware, ctx) -> None:
    """After blocking a duplicate, controller._pending_action is set to None."""
    await middleware.execute(ctx)

    ctx2 = ToolInvocationContext(
        controller=ctx.controller,
        action=CmdRunAction(command='echo hello'),
        state=MagicMock(),
    )
    await middleware.execute(ctx2)
    assert ctx2.controller._pending_action is None
