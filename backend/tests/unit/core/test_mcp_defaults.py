"""Tests for default user MCP server definitions."""

from __future__ import annotations

from backend.core.config.mcp_defaults import (
    DEFAULT_USER_MCP_SERVERS,
    default_user_mcp_config,
)


def test_default_user_mcp_config_includes_operator_servers() -> None:
    cfg = default_user_mcp_config()
    names = {s['name'] for s in cfg['servers']}
    assert cfg['enabled'] is True
    assert names == {s['name'] for s in DEFAULT_USER_MCP_SERVERS}
    assert names == {'shadcn', 'github', 'rigour'}
