from __future__ import annotations

from types import SimpleNamespace

from backend.integrations.mcp.mcp_tool_aliases import (
    _slugify_segment,
    prepare_mcp_tool_exposed_names,
)
from backend.integrations.mcp.tool import MCPClientTool


class _Client:
    def __init__(self, server_name: str, tools: list[MCPClientTool]) -> None:
        self._server_config = SimpleNamespace(name=server_name)
        self.tools = tools
        self.tool_map: dict[str, MCPClientTool] = {t.name: t for t in tools}
        self.exposed_to_protocol: dict[str, str] = {}
        self.alias_args = None

    def register_alias_context(self, mcps, reserved) -> None:  # noqa: ANN001
        self.alias_args = (mcps, reserved)


def _tool(name: str) -> MCPClientTool:
    return MCPClientTool(name=name, description='d', inputSchema={'type': 'object'})


def test_slugify_segment_basic_and_fallback() -> None:
    assert _slugify_segment('Server Name!') == 'server_name'
    assert _slugify_segment('', fallback='x') == 'x'


def test_prepare_mcp_tool_exposed_names_keeps_unique_tools() -> None:
    c = _Client('srv', [_tool('fetch_data'), _tool('health')])
    prepare_mcp_tool_exposed_names([c], reserved={'shell'})
    assert [t.name for t in c.tools] == ['fetch_data', 'health']
    assert c.exposed_to_protocol == {'fetch_data': 'fetch_data', 'health': 'health'}
    assert c.alias_args is not None


def test_prepare_mcp_tool_exposed_names_resolves_collisions() -> None:
    c1 = _Client('alpha', [_tool('search')])
    c2 = _Client('beta server', [_tool('search'), _tool('search')])
    prepare_mcp_tool_exposed_names([c1, c2], reserved={'search'})

    names_1 = [t.name for t in c1.tools]
    names_2 = [t.name for t in c2.tools]
    assert names_1[0].startswith('mcp_alpha_search')
    assert names_2[0].startswith('mcp_beta_server_search')
    assert names_2[1].startswith('mcp_beta_server_search')
    assert names_2[0] != names_2[1]
    for exposed, protocol in c2.exposed_to_protocol.items():
        assert protocol == 'search'
        assert exposed in c2.tool_map

