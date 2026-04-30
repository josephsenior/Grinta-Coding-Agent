from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.ledger.action import CmdRunAction
from backend.orchestration.middleware.destructive_command import (
    DestructiveCommandMiddleware,
)
from backend.orchestration.tool_pipeline import ToolInvocationContext


def _ctx(command: str = 'echo ok') -> ToolInvocationContext:
    controller = SimpleNamespace(runtime=SimpleNamespace(workspace_dir='C:/ws'))
    state = SimpleNamespace(sid='s1')
    action = CmdRunAction(command=command)
    return ToolInvocationContext(controller=controller, action=action, state=state)


@pytest.mark.asyncio
async def test_execute_noop_when_disabled_or_not_destructive() -> None:
    mw = DestructiveCommandMiddleware(workspace_path='C:/ws', enabled=False)
    ctx = _ctx('git reset --hard HEAD~1')
    await mw.execute(ctx)
    assert ctx.metadata == {}

    mw2 = DestructiveCommandMiddleware(workspace_path='C:/ws', enabled=True)
    ctx2 = _ctx('echo hello')
    await mw2.execute(ctx2)
    assert ctx2.metadata == {}


@pytest.mark.asyncio
async def test_get_manager_disables_when_workspace_invalid() -> None:
    mw = DestructiveCommandMiddleware(workspace_path='', enabled=True)
    ctx = _ctx('git reset --hard HEAD~1')
    m = mw._get_manager(ctx)
    assert m is None
    assert mw._enabled is False


@pytest.mark.asyncio
async def test_execute_handles_checkpoint_creation_failure() -> None:
    mw = DestructiveCommandMiddleware(workspace_path='C:/ws', enabled=True)
    ctx = _ctx('git clean -fdx')
    manager = MagicMock()
    manager.create_checkpoint.side_effect = RuntimeError('boom')

    with (
        patch('os.path.isdir', return_value=True),
        patch(
            'backend.core.rollback.rollback_manager.RollbackManager',
            return_value=manager,
        ),
    ):
        await mw.execute(ctx)

    assert ctx.metadata['destructive_command'] == 'git-clean'
    assert 'destructive_checkpoint_id' not in ctx.metadata


@pytest.mark.asyncio
async def test_execute_uses_runtime_workspace_when_not_provided() -> None:
    mw = DestructiveCommandMiddleware(workspace_path=None, enabled=True)
    ctx = _ctx('git push --force')
    manager = MagicMock()
    manager.create_checkpoint.return_value = 'cp-9'

    with (
        patch('os.path.isdir', return_value=True),
        patch(
            'backend.core.rollback.rollback_manager.RollbackManager',
            return_value=manager,
        ),
    ):
        await mw.execute(ctx)

    assert ctx.metadata['destructive_checkpoint_id'] == 'cp-9'
    assert ctx.metadata['rollback_checkpoint_id'] == 'cp-9'
