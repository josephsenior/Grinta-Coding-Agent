"""Integration tests wiring runtime executor, MCP bootstrap/fetch, and LSP client."""

from __future__ import annotations

import typing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config.mcp_config import MCPConfig, MCPServerConfig
from backend.execution.server.action_execution_server import (
    RuntimeExecutor,
    resolve_workspace_path,
)
from backend.integrations.mcp import mcp_utils as mu
from backend.integrations.mcp.mcp_bootstrap_status import (
    get_mcp_bootstrap_status,
    reset_mcp_bootstrap_status,
)
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import (
    ErrorObservation,
    LspQueryObservation,
    MCPObservation,
)
from backend.utils.lsp.lsp_client import LspClient, LspLocation, LspResult, LspSymbol


@pytest.fixture(autouse=True)
def _reset_mcp_bootstrap() -> typing.Generator[None, None, None]:
    reset_mcp_bootstrap_status()
    yield
    reset_mcp_bootstrap_status()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_mcp_tools_disabled_records_bootstrap() -> None:
    cfg = MCPConfig(enabled=False, servers=[])
    out = await mu.fetch_mcp_tools_from_config(cfg)
    assert out == []
    assert get_mcp_bootstrap_status()['state'] == 'mcp_disabled'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_mcp_tools_no_servers_configured() -> None:
    cfg = MCPConfig(enabled=True, servers=[])
    out = await mu.fetch_mcp_tools_from_config(cfg)
    assert out == []
    st = get_mcp_bootstrap_status()
    assert st['state'] == 'no_servers_configured'
    assert st['configured_server_count'] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_mcp_tools_no_clients_sets_bootstrap_and_returns_wrappers(
    tmp_path,
) -> None:
    cfg = MCPConfig(
        enabled=True,
        servers=[
            MCPServerConfig(
                name='stub-remote',
                type='sse',
                url='http://127.0.0.1:59999/unreachable',
            ),
        ],
    )
    with patch(
        'backend.integrations.mcp.mcp_utils.create_mcps',
        new_callable=AsyncMock,
        return_value=[],
    ):
        tools = await mu.fetch_mcp_tools_from_config(cfg)

    assert isinstance(tools, list)
    # No remote tools: wrapper_tool_params([]) adds nothing — degraded discovery is empty.
    assert tools == []
    st = get_mcp_bootstrap_status()
    assert st['state'] == 'no_clients_connected'
    assert st['connected_client_count'] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_executor_call_tool_mcp_truncates_large_payload(
    tmp_path,
) -> None:
    work = str(tmp_path)
    ex = RuntimeExecutor([], work, 'user', 1, enable_browser=False)
    huge = 'Z' * 600_000
    obs_in = MCPObservation(content=huge, name='t', arguments={})

    ex._mcp_clients = [MagicMock()]  # noqa: SLF001
    ex._mcp_servers_resolved = []  # noqa: SLF001

    act = MCPAction(name='any-tool', arguments={})
    with patch(
        'backend.integrations.mcp.mcp_utils.call_tool_mcp',
        new_callable=AsyncMock,
        return_value=obs_in,
    ):
        out = await ex.call_tool_mcp(act)

    assert isinstance(out, MCPObservation)
    assert len(out.content) <= len(huge)
    assert 'truncated' in out.content.lower() or len(out.content) < 100_000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_executor_lsp_query_observation_shape(tmp_path) -> None:
    py = tmp_path / 'mod.py'
    py.write_text('def foo():\n    return 1\n', encoding='utf-8')
    ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)

    action = LspQueryAction(
        file=str(py),
        command='find_definition',
        line=1,
        column=5,
    )
    loc = LspLocation(file=str(py), line=1, column=1)
    result = LspResult(
        available=True,
        locations=[loc],
        error='',
    )
    mock_client = MagicMock()
    mock_client.query.return_value = result
    with patch('backend.utils.lsp.lsp_client.get_lsp_client', return_value=mock_client):
        obs = await ex.lsp_query(action)

    assert isinstance(obs, LspQueryObservation)
    assert obs.tool_result['command'] == 'find_definition'  # type: ignore[index]
    assert obs.tool_result['file'] == str(py)  # type: ignore[index]
    assert obs.tool_result['available'] is True  # type: ignore[index]
    assert obs.tool_result['has_error'] is False  # type: ignore[index]
    assert 'Found' in obs.content


@pytest.mark.integration
def test_lsp_client_query_unknown_extension_is_unavailable(tmp_path) -> None:
    weird = tmp_path / 'data.xyzunknown'
    weird.write_text('x', encoding='utf-8')
    client = LspClient()
    res = client.query('hover', str(weird))
    assert res.available is False
    assert 'No LSP server' in (res.error or '') or not res.available


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_executor_call_tool_mcp_surfaces_error_observation(
    tmp_path,
) -> None:
    ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
    ex._mcp_clients = [MagicMock()]  # noqa: SLF001
    ex._mcp_servers_resolved = []  # noqa: SLF001
    act = MCPAction(name='x', arguments={})
    with patch(
        'backend.integrations.mcp.mcp_utils.call_tool_mcp',
        new_callable=AsyncMock,
        side_effect=ConnectionError('reset'),
    ):
        obs = await ex.call_tool_mcp(act)
    assert isinstance(obs, ErrorObservation)
    assert 'MCP' in obs.content


@pytest.mark.integration
def test_resolve_workspace_path_relative_to_working_dir(tmp_path: Path) -> None:
    workspace = tmp_path / 'ws'
    nested = workspace / 'pkg'
    nested.mkdir(parents=True)
    abs_file = tmp_path / 'outside_ref.txt'
    abs_file.write_text('x', encoding='utf-8')

    rel = resolve_workspace_path('sub/file.txt', str(nested), str(workspace))
    assert rel == (nested / 'sub/file.txt').resolve()

    with pytest.raises(ValueError, match='outside the workspace root'):
        resolve_workspace_path(str(abs_file), str(nested), str(workspace))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_action_strips_ansi_from_lsp_observation(tmp_path: Path) -> None:
    ex = RuntimeExecutor([], str(tmp_path), 'u', 1, enable_browser=False)
    action = LspQueryAction(
        file=str(tmp_path / 'a.py'),
        command='hover',
        line=1,
        column=1,
    )
    dirty = LspQueryObservation(
        content='\x1b[31mcolored\x1b[0m',
        available=True,
    )
    with patch.object(ex, 'lsp_query', new_callable=AsyncMock, return_value=dirty):
        obs = await ex.run_action(action)
    assert '\x1b' not in obs.content
    assert 'colored' in obs.content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_mcp_tools_create_mcps_failure_sets_fetch_failed() -> None:
    cfg = MCPConfig(
        enabled=True,
        servers=[
            MCPServerConfig(
                name='stub-remote',
                type='sse',
                url='http://127.0.0.1:59998/unreachable',
            ),
        ],
    )
    with patch(
        'backend.integrations.mcp.mcp_utils.create_mcps',
        new_callable=AsyncMock,
        side_effect=RuntimeError('simulated transport failure'),
    ):
        tools = await mu.fetch_mcp_tools_from_config(cfg)

    assert tools == []
    st = get_mcp_bootstrap_status()
    assert st['state'] == 'fetch_failed'
    assert st['last_error'] is not None
    assert 'simulated' in st['last_error']


@pytest.mark.integration
def test_runtime_executor_initial_cwd_and_uninitialized(tmp_path: Path) -> None:
    root = str(tmp_path)
    ex = RuntimeExecutor([], root, 'u', 1, enable_browser=False)
    assert ex.initial_cwd == root
    assert ex.initialized() is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_action_browser_disabled_error_observation(tmp_path: Path) -> None:
    ex = RuntimeExecutor([], str(tmp_path), 'u', 1, enable_browser=False)
    action = BrowserToolAction(command='snapshot', params={})
    obs = await ex.run_action(action)
    assert isinstance(obs, ErrorObservation)
    assert 'disabled' in obs.content.lower() or 'Browser' in obs.content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_executor_lsp_list_symbols_observation(tmp_path: Path) -> None:
    py = tmp_path / 'sym.py'
    py.write_text('class Box:\n    pass\n', encoding='utf-8')
    ex = RuntimeExecutor([], str(tmp_path), 'u', 1, enable_browser=False)
    action = LspQueryAction(
        file=str(py),
        command='list_symbols',
        line=1,
        column=1,
    )
    result = LspResult(
        available=True,
        symbols=[LspSymbol(name='Box', kind='Class', line=1)],
    )
    mock_client = MagicMock()
    mock_client.query.return_value = result
    with patch('backend.utils.lsp.lsp_client.get_lsp_client', return_value=mock_client):
        obs = await ex.lsp_query(action)
    assert isinstance(obs, LspQueryObservation)
    assert 'Box' in obs.content
    assert 'Symbols' in obs.content or 'Class' in obs.content
