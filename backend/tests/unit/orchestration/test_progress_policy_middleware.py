from types import SimpleNamespace

import pytest

from backend.ledger.action import CmdRunAction
from backend.ledger.action.terminal import TerminalInputAction, TerminalReadAction
from backend.ledger.observation import CmdOutputObservation, ErrorObservation
from backend.orchestration.middleware.progress_policy import ProgressPolicyMiddleware
from backend.orchestration.tool_pipeline import ToolInvocationContext


def _ctx_for(action: CmdRunAction | TerminalInputAction) -> ToolInvocationContext:
    controller = SimpleNamespace()
    state = SimpleNamespace(extra_data={})
    return ToolInvocationContext(controller=controller, action=action, state=state)


@pytest.mark.asyncio
async def test_progress_policy_blocks_repeated_signature_without_progress() -> None:
    mw = ProgressPolicyMiddleware()
    ctx = _ctx_for(CmdRunAction(command='echo hi'))

    for _ in range(3):
        await mw.execute(ctx)
        assert ctx.blocked is False

    await mw.execute(ctx)
    assert ctx.blocked is True
    assert 'POLICY_GATE_REPLAN_REQUIRED' in (ctx.block_reason or '')


@pytest.mark.asyncio
async def test_progress_policy_resets_repeat_counter_on_progress() -> None:
    mw = ProgressPolicyMiddleware()
    ctx = _ctx_for(CmdRunAction(command='echo hi'))

    await mw.execute(ctx)
    await mw.execute(ctx)
    obs = CmdOutputObservation(content='updated', command='echo hi')
    await mw.observe(ctx, obs)

    ctx.blocked = False
    ctx.block_reason = None
    await mw.execute(ctx)
    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_progress_policy_ignores_error_observations_for_progress() -> None:
    mw = ProgressPolicyMiddleware()
    ctx = _ctx_for(CmdRunAction(command='echo hi'))
    await mw.execute(ctx)
    await mw.observe(ctx, ErrorObservation(content='boom'))

    await mw.execute(ctx)
    await mw.execute(ctx)
    await mw.execute(ctx)
    assert ctx.blocked is True


@pytest.mark.asyncio
async def test_progress_policy_blocks_repeated_terminal_input_without_progress() -> None:
    mw = ProgressPolicyMiddleware()
    act = TerminalInputAction(session_id='s', control='enter')
    ctx = _ctx_for(act)

    for _ in range(3):
        await mw.execute(ctx)
        assert ctx.blocked is False

    await mw.execute(ctx)
    assert ctx.blocked is True


def test_progress_policy_fingerprint_includes_terminal_control() -> None:
    a = TerminalInputAction(session_id='x', control='enter')
    b = TerminalInputAction(session_id='x', control='C-c')
    assert ProgressPolicyMiddleware._fingerprint_action(
        a
    ) != ProgressPolicyMiddleware._fingerprint_action(b)


@pytest.mark.asyncio
async def test_progress_policy_blocks_repeated_terminal_read_earlier() -> None:
    """Terminal read polls are gated sooner than generic tool repeats (PTY stall pattern)."""
    mw = ProgressPolicyMiddleware()
    act = TerminalReadAction(session_id='s1', mode='delta')
    ctx = _ctx_for(act)

    await mw.execute(ctx)
    assert ctx.blocked is False
    await mw.execute(ctx)
    assert ctx.blocked is False

    await mw.execute(ctx)
    assert ctx.blocked is True
    assert 'POLICY_GATE_REPLAN_REQUIRED' in (ctx.block_reason or '')
