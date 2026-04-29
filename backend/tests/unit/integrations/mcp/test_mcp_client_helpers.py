"""Unit tests for module-level helpers in backend.integrations.mcp.client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.integrations.mcp import client as mcp_client
from backend.integrations.mcp.client import MCPClient


def test_mcp_call_total_budget_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('APP_MCP_CALL_TOTAL_BUDGET_SEC', '12.5')
    assert mcp_client._mcp_call_total_budget_sec() == 12.5
    monkeypatch.setenv('APP_MCP_CALL_TOTAL_BUDGET_SEC', 'notfloat')
    assert mcp_client._mcp_call_total_budget_sec() == 180.0
    monkeypatch.setenv('APP_MCP_CALL_TOTAL_BUDGET_SEC', '-1')
    assert mcp_client._mcp_call_total_budget_sec() == 180.0


def test_mcp_reconnect_session_timeout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('APP_MCP_RECONNECT_SESSION_TIMEOUT_SEC', '7')
    assert mcp_client._mcp_reconnect_session_timeout_sec() == 7.0
    monkeypatch.setenv('APP_MCP_RECONNECT_SESSION_TIMEOUT_SEC', 'x')
    assert mcp_client._mcp_reconnect_session_timeout_sec() == 90.0


def test_is_exception_group_false() -> None:
    assert mcp_client._is_exception_group(ValueError('x')) is False


def test_reapply_mcp_tool_aliases_noop_without_context() -> None:
    c = MCPClient()
    c._reapply_mcp_tool_aliases()  # should not raise


def test_register_alias_context() -> None:
    c = MCPClient()
    peer = MagicMock()
    c.register_alias_context([peer], frozenset({'a'}))
    assert c._mcp_alias_peers == [peer]  # noqa: SLF001
    assert c._mcp_alias_reserved == frozenset({'a'})  # noqa: SLF001


def test_build_http_headers() -> None:
    c = MCPClient()
    h = c._build_http_headers('k', 'conv-1')  # noqa: SLF001
    assert h['Authorization'] == 'Bearer k'
    assert h['X-App-ServerConversation-ID'] == 'conv-1'


@pytest.mark.asyncio
async def test_close_client_context_exception_group_path() -> None:
    c = MCPClient()
    eg = ExceptionGroup('g', [OSError('x')])  # type: ignore[name-defined]
    cli = MagicMock()
    cli.__aexit__ = AsyncMock(side_effect=eg)
    with patch.object(mcp_client, '_is_exception_group', return_value=True):
        await c._close_client_context(cli)  # noqa: SLF001
