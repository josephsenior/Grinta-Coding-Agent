"""Bundled MCP servers that power first-party native tools (not user-facing MCP extensions)."""

from __future__ import annotations

from typing import Any

# Stdio/hosted servers wired internally — hidden from TUI MCP lists and prompt hints.
NATIVE_MCP_SERVER_NAMES = frozenset({'context7', 'exa', 'fetch'})

# Legacy alias kept out of user-facing surfaces (runtime app-mcp channel).
_INTERNAL_MCP_SERVER_NAMES = NATIVE_MCP_SERVER_NAMES | frozenset({'app-mcp'})

EXA_WEB_SEARCH_MCP_TOOL = 'web_search_exa'
EXA_WEB_FETCH_MCP_TOOL = 'web_fetch_exa'
FALLBACK_FETCH_MCP_TOOL = 'fetch'
CONTEXT7_RESOLVE_MCP_TOOL = 'resolve-library-id'
CONTEXT7_QUERY_MCP_TOOL = 'query-docs'

MCP_TOOLS_HIDDEN_BY_NATIVE_WEB = frozenset(
    {
        EXA_WEB_SEARCH_MCP_TOOL,
        EXA_WEB_FETCH_MCP_TOOL,
        FALLBACK_FETCH_MCP_TOOL,
        'crawling_exa',
        'deep_search_exa',
    }
)

MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS = frozenset(
    {
        CONTEXT7_RESOLVE_MCP_TOOL,
        CONTEXT7_QUERY_MCP_TOOL,
    }
)

MCP_TOOLS_HIDDEN_BY_NATIVE_FACADES = (
    MCP_TOOLS_HIDDEN_BY_NATIVE_WEB | MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS
)


def is_user_visible_mcp_server(name: str) -> bool:
    """Return True when an MCP server should appear in UI / operator-facing lists."""
    return (name or '').strip() not in _INTERNAL_MCP_SERVER_NAMES


def count_user_visible_mcp_servers(config: Any) -> int:
    """Count configured MCP servers the operator manages (excludes native backends)."""
    mcp = getattr(config, 'mcp', None)
    servers = getattr(mcp, 'servers', None) or []
    return sum(1 for s in servers if is_user_visible_mcp_server(getattr(s, 'name', '')))


def filter_user_visible_mcp_server_dicts(
    servers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [s for s in servers if is_user_visible_mcp_server(str(s.get('name') or ''))]


def filter_user_visible_mcp_server_configs(servers: list[Any]) -> list[Any]:
    return [s for s in servers if is_user_visible_mcp_server(getattr(s, 'name', ''))]
