from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ledger.action import CmdRunAction
from backend.ledger.action.agent import BlackboardAction
from backend.orchestration.middleware.blackboard import BlackboardMiddleware
from backend.orchestration.middleware.context_window import ContextWindowMiddleware
from backend.orchestration.middleware.cost_quota import CostQuotaMiddleware
from backend.orchestration.middleware.destructive_command import (
    DestructiveCommandMiddleware,
    _scan_command,
)
from backend.orchestration.middleware.safety_validator import (
    SafetyValidatorMiddleware,
)
from backend.orchestration.middleware.telemetry import TelemetryMiddleware
from backend.orchestration.tool_pipeline import ToolInvocationContext


def _controller() -> MagicMock:
    c = MagicMock()
    c.id = 'sid-1'
    c.event_stream = MagicMock()
    c.state = MagicMock()
    c.state.iteration_flag = MagicMock(current_value=2)
    c.state.agent_state = SimpleNamespace(value='running')
    c.state.last_error = ''
    c._pending_action = object()
    c.autonomy_controller = SimpleNamespace(autonomy_level='full')
    c.agent = SimpleNamespace(llm=None)
    c.config = SimpleNamespace(blackboard=None)
    return c


def _ctx(controller: MagicMock, action: Any | None = None) -> ToolInvocationContext:
    if action is None:
        action = MagicMock(runnable=True)
    return ToolInvocationContext(
        controller=controller, action=action, state=controller.state
    )


@pytest.mark.asyncio
async def test_blackboard_middleware_get_set_keys_and_unknown() -> None:
    controller = _controller()
    middleware = BlackboardMiddleware(controller)
    bb = AsyncMock()
    controller.config.blackboard = bb
    bb.get.return_value = {'k': 'v'}
    bb.keys.return_value = ['k']

    get_action = BlackboardAction(command='get', key='k', value='')
    set_action = BlackboardAction(command='set', key='k', value='v2')
    keys_action = BlackboardAction(command='keys', key='', value='')
    bad_action = BlackboardAction(command='nope', key='', value='')

    for action in (get_action, set_action, keys_action, bad_action):
        ctx = _ctx(controller, action)  # type: ignore[arg-type]
        await middleware.execute(ctx)
        assert ctx.blocked is True
        assert ctx.metadata.get('handled') is True

    assert controller.event_stream.add_event.call_count == 4
    bb.set.assert_awaited_once_with('k', 'v2')


@pytest.mark.asyncio
async def test_blackboard_middleware_ignores_non_blackboard_action() -> None:
    controller = _controller()
    middleware = BlackboardMiddleware(controller)
    normal_action = MagicMock()
    with patch('backend.ledger.action.agent.BlackboardAction', new=type('B', (), {})):
        ctx = _ctx(controller, normal_action)
        await middleware.execute(ctx)
    assert ctx.blocked is False
    controller.event_stream.add_event.assert_not_called()


@pytest.mark.asyncio
async def test_context_window_middleware_emits_alerts_and_sets_pressure() -> None:
    controller = _controller()
    usage = SimpleNamespace(prompt_tokens=900, context_window=1000)
    controller.agent.llm = SimpleNamespace(
        metrics=SimpleNamespace(token_usages=[usage])
    )
    controller.state.set_memory_pressure = MagicMock()
    middleware = ContextWindowMiddleware(controller)

    await middleware.observe(_ctx(controller), observation=None)
    assert controller.event_stream.add_event.call_count >= 1
    controller.state.set_memory_pressure.assert_called_once()


@pytest.mark.asyncio
async def test_context_window_middleware_no_metrics_noop() -> None:
    controller = _controller()
    controller.agent.llm = SimpleNamespace(metrics=SimpleNamespace(token_usages=[]))
    middleware = ContextWindowMiddleware(controller)
    await middleware.observe(_ctx(controller), observation=None)
    controller.event_stream.add_event.assert_not_called()


@pytest.mark.asyncio
async def test_cost_quota_middleware_records_snapshot_and_annotates() -> None:
    controller = _controller()
    metrics = SimpleNamespace(accumulated_cost=1.0, max_budget_per_task=3.0)
    controller.agent.llm = SimpleNamespace(metrics=metrics)
    middleware = CostQuotaMiddleware(controller)
    ctx = _ctx(controller)
    observation = SimpleNamespace(content='ok')

    await middleware.execute(ctx)
    metrics.accumulated_cost = 1.5
    await middleware.observe(ctx, observation)  # type: ignore[arg-type]

    assert 'cost_snapshot' in ctx.metadata
    assert '<COST_FOOTPRINT>' in observation.content
    assert 'budget_remaining' in observation.content


@pytest.mark.asyncio
async def test_cost_quota_middleware_skips_non_positive_delta() -> None:
    controller = _controller()
    metrics = SimpleNamespace(accumulated_cost=1.0, max_budget_per_task=None)
    controller.agent.llm = SimpleNamespace(metrics=metrics)
    middleware = CostQuotaMiddleware(controller)
    ctx = _ctx(controller)
    await middleware.execute(ctx)
    observation = SimpleNamespace(content='x')
    await middleware.observe(ctx, observation)  # type: ignore[arg-type]
    assert observation.content == 'x'


def test_scan_command_detects_and_ignores_patterns() -> None:
    assert _scan_command('git reset --hard HEAD~1') == 'git-reset-hard'
    assert _scan_command('rm -rf /tmp/abc') == 'rm-recursive-force'
    assert _scan_command('echo hello world') is None


@pytest.mark.asyncio
async def test_destructive_command_middleware_creates_checkpoint() -> None:
    controller = _controller()
    ctx = _ctx(controller, CmdRunAction(command='git push --force origin main'))  # type: ignore[arg-type]
    ctx.state = SimpleNamespace(sid='S1')  # type: ignore[assignment]
    middleware = DestructiveCommandMiddleware(workspace_path='C:/tmp', enabled=True)
    manager = MagicMock()
    manager.create_checkpoint.return_value = 'cp-1'

    with (
        patch('os.path.isdir', return_value=True),
        patch(
            'backend.core.rollback.rollback_manager.RollbackManager',
            return_value=manager,
        ),
    ):
        await middleware.execute(ctx)

    assert ctx.metadata['destructive_command'] == 'git-push-force'
    assert ctx.metadata['destructive_checkpoint_id'] == 'cp-1'
    assert ctx.metadata['rollback_available'] is True


@pytest.mark.asyncio
async def test_safety_validator_middleware_blocks_disallowed_action() -> None:
    controller = _controller()
    controller.safety_validator = MagicMock()
    controller.safety_validator.validate = AsyncMock(
        return_value=SimpleNamespace(
            allowed=False,
            blocked_reason='dangerous operation',
            audit_id='audit-1',
        )
    )
    action = MagicMock(runnable=True)
    ctx = _ctx(controller, action)
    middleware = SafetyValidatorMiddleware(controller)

    await middleware.execute(ctx)

    assert ctx.blocked is True
    assert ctx.metadata['audit_id'] == 'audit-1'
    assert ctx.metadata['handled'] is True
    assert controller._pending_action is None
    controller.event_stream.add_event.assert_called_once()


@pytest.mark.asyncio
async def test_safety_validator_middleware_allows_and_skips_non_runnable() -> None:
    controller = _controller()
    controller.safety_validator = MagicMock()
    controller.safety_validator.validate = AsyncMock(
        return_value=SimpleNamespace(allowed=True, blocked_reason='', audit_id=None)
    )
    middleware = SafetyValidatorMiddleware(controller)

    non_runnable = _ctx(controller, MagicMock(runnable=False))
    await middleware.execute(non_runnable)
    controller.safety_validator.validate.assert_not_awaited()

    runnable = _ctx(controller, MagicMock(runnable=True))
    await middleware.execute(runnable)
    assert runnable.blocked is False


@pytest.mark.asyncio
async def test_telemetry_middleware_execute_and_observe() -> None:
    controller = _controller()
    telemetry = MagicMock()
    with patch(
        'backend.orchestration.middleware.telemetry.ToolTelemetry.get_instance',
        return_value=telemetry,
    ):
        middleware = TelemetryMiddleware(controller)

    ctx = _ctx(controller)
    await middleware.execute(ctx)
    await middleware.observe(ctx, observation=SimpleNamespace(content='ok'))  # type: ignore[arg-type]

    telemetry.on_execute.assert_called_once_with(ctx)
    telemetry.on_observe.assert_called_once()
