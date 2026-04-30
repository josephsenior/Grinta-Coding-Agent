"""Unit tests for MCPProxyManager (mocked FastMCP)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config.mcp_config import MCPServerConfig
from backend.execution.mcp.proxy.mcp_proxy_manager import MCPProxyManager


def test_mcp_proxy_manager_initialize_skips_when_empty_config() -> None:
    mgr = MCPProxyManager()
    mgr.initialize(None)
    assert mgr.proxy is None


def test_mcp_proxy_manager_initialize_with_server_calls_as_proxy() -> None:
    srv = MCPServerConfig(name='t', type='sse', url='http://127.0.0.1:9/sse')
    mgr = MCPProxyManager()
    fake_proxy = MagicMock()
    with patch(
        'backend.execution.mcp.proxy.mcp_proxy_manager.FastMCP'
    ) as FM:
        FM.as_proxy.return_value = fake_proxy
        mgr.initialize([srv])
    FM.as_proxy.assert_called_once()
    assert mgr.proxy is fake_proxy


@pytest.mark.asyncio
async def test_mount_to_app_raises_when_proxy_missing() -> None:
    mgr = MCPProxyManager()
    mgr.config['mcpServers'] = {'x': {}}
    app = MagicMock()
    with pytest.raises(ValueError, match='not initialized'):
        await mgr.mount_to_app(app)


@pytest.mark.asyncio
async def test_mount_to_app_skips_when_no_servers() -> None:
    mgr = MCPProxyManager()
    await mgr.mount_to_app(MagicMock())
