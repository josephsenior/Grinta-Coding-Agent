from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.execution.server.action_execution_server import RuntimeExecutor
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import ErrorObservation


@pytest.fixture
def mock_executor(tmp_path: Path):
    with (
        patch('os.makedirs'),
        patch('backend.execution.server.action_execution_server.SessionManager'),
    ):
        ex = RuntimeExecutor(
            plugins_to_load=[],
            work_dir=str(tmp_path / 'ws'),
            username='u',
            user_id=1,
            enable_browser=False,
            security_config=SimpleNamespace(execution_profile='standard'),
        )
        ex.session_manager = MagicMock()
        ex.debug_manager = MagicMock()
        ex.memory_monitor = MagicMock()
        return ex


@pytest.mark.asyncio
async def test_call_tool_mcp_returns_error_observation_on_exception(
    mock_executor,
) -> None:
    with patch(
        'backend.integrations.mcp.mcp_utils.create_mcps',
        side_effect=RuntimeError('boom'),
    ):
        obs = await mock_executor.call_tool_mcp(MCPAction(name='x', arguments={}))
    assert isinstance(obs, ErrorObservation)
    assert 'MCP tool call failed' in obs.content


@pytest.mark.asyncio
async def test_call_tool_mcp_success_truncates_content(mock_executor) -> None:
    fake_obs = SimpleNamespace(content='hello world')
    with (
        patch(
            'backend.core.config.config_loader.load_app_config',
            return_value=SimpleNamespace(
                mcp=SimpleNamespace(servers=[], mcp_exposed_name_reserved=frozenset())
            ),
        ),
        patch(
            'backend.core.config.mcp_config._filter_windows_stdio_servers',
            side_effect=lambda s: s,
        ),
        patch(
            'backend.integrations.mcp.mcp_utils.create_mcps', AsyncMock(return_value=[])
        ),
        patch(
            'backend.integrations.mcp.mcp_utils.call_tool_mcp',
            AsyncMock(return_value=fake_obs),
        ),
        patch(
            'backend.execution.server.action_execution_server.get_max_edit_observation_chars',
            return_value=5,
        ),
        patch(
            'backend.execution.server.action_execution_server.truncate_large_text',
            side_effect=lambda t, m, label='': t[:m],
        ),
    ):
        obs = await mock_executor.call_tool_mcp(MCPAction(name='x', arguments={}))
    assert obs.content == 'hello'


@pytest.mark.asyncio
async def test_lsp_query_success_and_failure(mock_executor) -> None:
    action = LspQueryAction(command='definition', file='a.py', line=1, column=1)
    success_result = SimpleNamespace(
        available=True,
        error='',
        format_text=lambda _cmd: 'ok',
    )
    with patch('backend.utils.lsp.lsp_client.LspClient') as cls:
        cls.return_value.query.return_value = success_result
        ok = await mock_executor.lsp_query(action)
    assert ok.__class__.__name__ == 'LspQueryObservation'
    assert ok.tool_result['available'] is True

    with patch(
        'backend.utils.lsp.lsp_client.LspClient', side_effect=RuntimeError('lsp down')
    ):
        bad = await mock_executor.lsp_query(action)
    assert isinstance(bad, ErrorObservation)
    assert bad.tool_result['available'] is False  # type: ignore[index]


@pytest.mark.asyncio
async def test_browser_tool_disabled_and_enabled_paths(mock_executor) -> None:
    disabled = await mock_executor.browser_tool(
        BrowserToolAction(command='goto', params={})
    )
    assert isinstance(disabled, ErrorObservation)
    assert 'disabled' in disabled.content

    mock_executor.enable_browser = True
    browser = MagicMock()
    browser.execute = AsyncMock(return_value=SimpleNamespace(content='ok'))
    with patch('backend.execution.browser.GrintaNativeBrowser', return_value=browser):
        out = await mock_executor.browser_tool(
            BrowserToolAction(command='goto', params={'url': 'https://a'})
        )
    assert out.content == 'ok'


def test_close_cleans_resources(mock_executor) -> None:
    c1 = MagicMock()
    c1.disconnect = AsyncMock(return_value=None)
    mock_executor._mcp_clients = [c1]
    native = MagicMock()
    native.shutdown = AsyncMock(return_value=None)
    mock_executor._native_browser = native
    mock_executor.browser = MagicMock()

    with patch(
        'backend.utils.async_helpers.async_utils.call_async_from_sync',
        return_value=None,
    ):
        mock_executor.close()

    mock_executor.debug_manager.close_all.assert_called_once()
    mock_executor.session_manager.close_all.assert_called_once()
    mock_executor.memory_monitor.stop_monitoring.assert_called_once()
