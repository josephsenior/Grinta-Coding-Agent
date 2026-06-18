from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

import backend.execution.action_execution_server as aes
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import ErrorObservation
from backend.utils.lsp.lsp_client import LspResult


def test_resolve_workspace_path_relative_and_absolute(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    nested = workspace / 'sub'
    nested.mkdir(parents=True)
    absolute = tmp_path / 'abs.txt'
    absolute.write_text('x', encoding='utf-8')

    # Relative paths resolve against working_dir (nested)
    rel = aes.resolve_workspace_path('x.txt', str(nested), str(workspace))
    assert rel == (nested / 'x.txt').resolve()

    # Absolute paths that are within workspace are allowed
    abs_within = workspace / 'root_file.txt'
    abs_within.write_text('y', encoding='utf-8')
    abs_out = aes.resolve_workspace_path(str(abs_within), str(nested), str(workspace))
    assert abs_out == abs_within.resolve()


def test_resolve_workspace_path_rejects_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    workspace.mkdir(parents=True)
    nested = workspace / 'sub'
    nested.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir(parents=True)

    # Absolute path outside workspace should be rejected
    with pytest.raises(ValueError, match='outside the workspace root'):
        aes.resolve_workspace_path(
            str(outside / 'evil.txt'), str(nested), str(workspace)
        )

    # Relative path that escapes workspace should be rejected
    with pytest.raises(ValueError, match='outside the workspace root'):
        aes.resolve_workspace_path('../../outside.txt', str(nested), str(workspace))


def test_try_compile_user_regex_valid_and_invalid() -> None:
    ok, err = aes.try_compile_user_regex(r'foo\d+')
    assert ok is not None
    assert err is None

    bad, bad_err = aes.try_compile_user_regex('(')
    assert bad is None
    assert isinstance(bad_err, str)


def test_get_client_raises_when_uninitialized() -> None:
    old = aes.client
    try:
        aes.client = None
        with pytest.raises(ReferenceError):
            aes.get_client()
    finally:
        aes.client = old


def test_get_client_returns_global_client() -> None:
    old = aes.client
    fake = MagicMock()
    try:
        aes.client = fake
        assert aes.get_client() is fake
    finally:
        aes.client = old


def test_get_mcp_proxy_reads_global() -> None:
    old = aes.mcp_proxy_manager
    try:
        aes.mcp_proxy_manager = SimpleNamespace(name='proxy')  # type: ignore[assignment]
        assert aes.get_mcp_proxy().name == 'proxy'  # type: ignore[union-attr]
    finally:
        aes.mcp_proxy_manager = old


def test_get_uvicorn_json_log_config_shape() -> None:
    cfg = aes.get_uvicorn_json_log_config()
    assert cfg['version'] == 1
    assert 'formatters' in cfg
    assert 'handlers' in cfg
    assert 'loggers' in cfg
    assert cfg['loggers']['uvicorn']['level'] == 'INFO'


@pytest.mark.asyncio
async def test_lifespan_fails_when_prewarm_check_fails() -> None:
    app = FastAPI()
    with (
        patch(
            'backend.utils.model_prewarm.ensure_models_available',
            side_effect=RuntimeError('missing model'),
        ),
        patch(
            'backend.utils.model_prewarm.get_default_models_to_prewarm', return_value=[]
        ),
    ):
        with pytest.raises(RuntimeError):
            async with aes.lifespan(app):
                pass


@pytest.mark.asyncio
async def test_lifespan_runs_initialize_and_shutdown_calls_client_close() -> None:
    app = FastAPI()
    old_client = aes.client
    old_task = aes.initialization_task
    old_proxy = aes.mcp_proxy_manager
    fake_client = MagicMock()
    fake_proxy = MagicMock()

    async def _init_background(_: FastAPI) -> None:
        await asyncio.sleep(0.01)

    try:
        aes.client = fake_client
        aes.mcp_proxy_manager = fake_proxy
        aes._initialize_background = _init_background  # type: ignore[attr-defined]

        with (
            patch(
                'backend.utils.model_prewarm.ensure_models_available', return_value={}
            ),
            patch(
                'backend.utils.model_prewarm.get_default_models_to_prewarm',
                return_value=['a/b'],
            ),
        ):
            async with aes.lifespan(app):
                assert aes.initialization_task is not None
                await asyncio.sleep(0.02)

        fake_client.close.assert_called_once()
    finally:
        aes.client = old_client
        aes.initialization_task = old_task
        aes.mcp_proxy_manager = old_proxy


@pytest.mark.asyncio
async def test_lifespan_cancels_pending_initialization_task_on_shutdown() -> None:
    app = FastAPI()
    old_task = aes.initialization_task

    async def _init_background(_: FastAPI) -> None:
        await asyncio.sleep(5)

    try:
        aes._initialize_background = _init_background  # type: ignore[attr-defined]
        with (
            patch(
                'backend.utils.model_prewarm.ensure_models_available', return_value={}
            ),
            patch(
                'backend.utils.model_prewarm.get_default_models_to_prewarm',
                return_value=[],
            ),
        ):
            async with aes.lifespan(app):
                assert aes.initialization_task is not None
                assert aes.initialization_task.done() is False
    finally:
        aes.initialization_task = old_task


def test_action_request_model() -> None:
    ar = aes.ActionRequest(event={'k': 1})
    assert ar.event == {'k': 1}


@pytest.mark.asyncio
async def test_runtime_executor_hard_kill(tmp_path: Path) -> None:
    ex = aes.RuntimeExecutor([], str(tmp_path), 'u', 1, False)
    ex.debug_manager = MagicMock()
    ex.session_manager = MagicMock()
    await ex.hard_kill()
    ex.debug_manager.close_all.assert_called_once()
    ex.session_manager.close_all.assert_called_once()


@pytest.mark.asyncio
async def test_browser_tool_disabled_returns_error(tmp_path: Path) -> None:
    ex = aes.RuntimeExecutor([], str(tmp_path), 'u', 1, enable_browser=False)
    obs = await ex.browser_tool(BrowserToolAction(command='navigate'))
    assert isinstance(obs, ErrorObservation)


@pytest.mark.asyncio
async def test_lsp_query_success_and_failure(tmp_path: Path) -> None:
    py = tmp_path / 'm.py'
    py.write_text('x = 1\n', encoding='utf-8')
    ex = aes.RuntimeExecutor([], str(tmp_path), 'u', 1, False)
    action = LspQueryAction(file=str(py), command='hover', line=1, column=1)
    with patch('backend.utils.lsp.lsp_client.LspClient') as LC:
        LC.return_value.query.return_value = LspResult(
            available=True, hover_text='docs'
        )
        obs = await ex.lsp_query(action)
    assert 'docs' in obs.content

    with patch(
        'backend.utils.lsp.lsp_client.LspClient',
        side_effect=RuntimeError('boom'),
    ):
        err_obs = await ex.lsp_query(action)
    assert isinstance(err_obs, ErrorObservation)


@pytest.mark.asyncio
async def test_call_tool_mcp_returns_error_observation_on_failure(
    tmp_path: Path,
) -> None:
    ex = aes.RuntimeExecutor([], str(tmp_path), 'u', 1, False)
    ex._mcp_clients = [MagicMock()]  # noqa: SLF001
    ex._mcp_servers_resolved = []  # noqa: SLF001
    act = MCPAction(name='tool_x', arguments={})
    with patch(
        'backend.integrations.mcp.mcp_utils.call_tool_mcp',
        side_effect=ValueError('bad'),
    ):
        obs = await ex.call_tool_mcp(act)
    assert isinstance(obs, ErrorObservation)
    assert 'failed' in obs.content.lower()


def test_runtime_executor_close_sync_cleanup(tmp_path: Path) -> None:
    ex = aes.RuntimeExecutor([], str(tmp_path), 'u', 1, False)
    ex.debug_manager = MagicMock()
    ex.session_manager = MagicMock()
    ex.memory_monitor = MagicMock()
    ex._mcp_clients = None  # noqa: SLF001
    ex.close()
    ex.debug_manager.close_all.assert_called_once()
    ex.session_manager.close_all.assert_called_once()
    ex.memory_monitor.stop_monitoring.assert_called_once()
