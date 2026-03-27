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

    def test_reserved_collision_uses_numeric_suffix_when_base_taken(self):
        """When base alias and _2 are reserved, pick _3."""
        client = MCPClient(
            tools=[_tool("a")],
            tool_map={"a": _tool("a")},
        )
        client._server_config = SimpleNamespace(name="special")
        reserved = {"a", "mcp_special_a", "mcp_special_a_2"}
        prepare_mcp_tool_exposed_names([client], reserved)
        assert [tool.name for tool in client.tools] == ["mcp_special_a_3"]
        assert client.exposed_to_protocol == {"mcp_special_a_3": "a"}

    def test_two_tools_same_protocol_name_in_one_client_second_is_aliased(self):
        client = MCPClient(
            tools=[_tool("dup"), _tool("dup")],
            tool_map={"dup": _tool("dup")},
        )
        client._server_config = None
        prepare_mcp_tool_exposed_names([client], set())
        names = [tool.name for tool in client.tools]
        assert names[0] == "dup"
        assert names[1] == "mcp_mcp_dup"

    def test_server_name_only_punctuation_yields_fallback_slug(self):
        client = MCPClient(
            tools=[_tool("x")],
            tool_map={"x": _tool("x")},
        )
        client._server_config = SimpleNamespace(name="@@@")
        prepare_mcp_tool_exposed_names([client], {"x"})
        assert [tool.name for tool in client.tools] == ["mcp_mcp_x"]
