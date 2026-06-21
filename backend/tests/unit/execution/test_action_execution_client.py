"""Tests for ActionExecutionClient MCP and HTTP helpers."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.execution.drivers.action_execution.action_execution_client import (
    ActionExecutionClient,
)
from backend.ledger.action import MCPAction
from backend.ledger.observation.mcp import MCPObservation
from backend.utils.http.http_session import HttpSession


def _make_client() -> ActionExecutionClient:
    client = ActionExecutionClient.__new__(ActionExecutionClient)
    client._action_server_session = HttpSession()
    client._mcp_clients = None
    client._mcp_servers_resolved = None
    client.config = MagicMock()
    client.config.mcp = MagicMock(servers=[])
    client._mcp_config = client.config.mcp
    cast(Any, client).action_execution_server_url = ''
    return client


def test_send_action_server_request_uses_http_session() -> None:
    client = _make_client()
    cast(Any, client).action_execution_server_url = 'http://127.0.0.1:9'

    with patch(
        'backend.execution.drivers.action_execution.action_execution_client.send_request'
    ) as send_request:
        mock_resp = MagicMock()
        send_request.return_value = mock_resp
        result = ActionExecutionClient._send_action_server_request(
            client, 'GET', '/ping'
        )
        assert result is mock_resp
        send_request.assert_called_once()
        session_arg, method, url = send_request.call_args[0]
        assert isinstance(session_arg, HttpSession)
        assert session_arg is client._action_server_session
        assert method == 'GET'
        assert url == 'http://127.0.0.1:9/ping'


def test_get_mcp_config_uses_local_config_without_remote_server() -> None:
    from backend.core.config.mcp_config import MCPServerConfig

    client = _make_client()
    client.config.mcp = MagicMock(
        servers=[
            MCPServerConfig(
                name='local',
                type='sse',
                url='http://127.0.0.1:8080/mcp',
                transport='sse',
            )
        ]
    )

    cfg = client.get_mcp_config()
    assert len(cfg.servers) == 1
    assert cfg.servers[0].name == 'local'


@pytest.mark.asyncio
async def test_call_tool_mcp_on_windows_uses_shared_runtime() -> None:
    client = _make_client()
    action = MCPAction(name='demo', arguments={'x': 1})
    expected = MCPObservation(content='ok')

    with patch(
        'backend.execution.utils.mcp_runtime.call_mcp_action',
        new=AsyncMock(return_value=(expected, ['client'], ['server'])),
    ) as call_mcp:
        obs = await client.call_tool_mcp(action)

    assert obs is expected
    assert client._mcp_clients == ['client']
    assert client._mcp_servers_resolved == ['server']
    call_mcp.assert_awaited_once()
