"""Tests for bundled native MCP backend visibility helpers."""

from __future__ import annotations

from types import SimpleNamespace

from backend.integrations.mcp.native_backends import (
    NATIVE_MCP_SERVER_NAMES,
    count_user_visible_mcp_servers,
    filter_user_visible_mcp_server_dicts,
    is_user_visible_mcp_server,
)


def test_native_mcp_servers_are_not_user_visible():
    for name in NATIVE_MCP_SERVER_NAMES:
        assert is_user_visible_mcp_server(name) is False
    assert is_user_visible_mcp_server('app-mcp') is False
    assert is_user_visible_mcp_server('github') is True


def test_filter_user_visible_mcp_server_dicts():
    rows = filter_user_visible_mcp_server_dicts(
        [
            {'name': 'exa', 'type': 'shttp'},
            {'name': 'github', 'type': 'stdio'},
            {'name': 'context7', 'type': 'stdio'},
        ]
    )
    assert rows == [{'name': 'github', 'type': 'stdio'}]


def test_count_user_visible_mcp_servers():
    config = SimpleNamespace(
        mcp=SimpleNamespace(
            servers=[
                SimpleNamespace(name='fetch'),
                SimpleNamespace(name='rigour'),
                SimpleNamespace(name='exa'),
            ]
        )
    )
    assert count_user_visible_mcp_servers(config) == 1
