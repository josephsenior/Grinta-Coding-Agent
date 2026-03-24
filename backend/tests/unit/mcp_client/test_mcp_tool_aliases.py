"""Tests for stable MCP tool alias generation."""

from types import SimpleNamespace

from backend.mcp_client.client import MCPClient
from backend.mcp_client.mcp_tool_aliases import prepare_mcp_tool_exposed_names
from backend.mcp_client.tool import MCPClientTool


def _tool(name: str) -> MCPClientTool:
    return MCPClientTool(name=name, description=f"{name} tool", inputSchema={})


class TestPrepareMcpToolExposedNames:
    def test_reserved_name_collision_gets_server_scoped_alias(self):
        client = MCPClient(
            tools=[_tool("search")],
            tool_map={"search": _tool("search")},
        )
        client._server_config = SimpleNamespace(name="Docs Server")

        prepare_mcp_tool_exposed_names([client], {"search"})

        assert [tool.name for tool in client.tools] == ["mcp_docs_server_search"]
        assert client.exposed_to_protocol == {"mcp_docs_server_search": "search"}
        assert "mcp_docs_server_search" in client.tool_map

    def test_duplicate_remote_names_are_disambiguated(self):
        client_a = MCPClient(
            tools=[_tool("lookup")],
            tool_map={"lookup": _tool("lookup")},
        )
        client_a._server_config = SimpleNamespace(name="alpha")
        client_b = MCPClient(
            tools=[_tool("lookup")],
            tool_map={"lookup": _tool("lookup")},
        )
        client_b._server_config = SimpleNamespace(name="beta")

        prepare_mcp_tool_exposed_names([client_a, client_b], set())

        assert [tool.name for tool in client_a.tools] == ["lookup"]
        assert [tool.name for tool in client_b.tools] == ["mcp_beta_lookup"]
        assert client_a.exposed_to_protocol == {"lookup": "lookup"}
        assert client_b.exposed_to_protocol == {"mcp_beta_lookup": "lookup"}
