"""Tests for backend.engines.orchestrator.tools.database."""
from __future__ import annotations

from backend.engines.orchestrator.tools.database import (
    create_database_connect_tool,
    create_database_query_tool,
    create_database_schema_tool,
    get_database_tools,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_func(tool: dict) -> dict:
    return tool["function"]


def _get_params(tool: dict) -> dict:
    return _get_func(tool)["parameters"]


def _required(tool: dict) -> list[str]:
    return _get_params(tool).get("required", [])


def _properties(tool: dict) -> dict:
    return _get_params(tool).get("properties", {})


# ---------------------------------------------------------------------------
# create_database_connect_tool
# ---------------------------------------------------------------------------


class TestCreateDatabaseConnectTool:
    def setup_method(self):
        self.tool = create_database_connect_tool()

    def test_returns_dict(self):
        assert isinstance(self.tool, dict)

    def test_name_is_database_connect(self):
        assert _get_func(self.tool)["name"] == "database_connect"

    def test_has_description(self):
        desc = _get_func(self.tool).get("description", "")
        assert len(desc) > 10

    def test_required_fields(self):
        req = _required(self.tool)
        assert "connection_name" in req
        assert "db_type" in req
        assert "env_prefix" in req

    def test_db_type_has_enum(self):
        props = _properties(self.tool)
        db_type = props["db_type"]
        assert "enum" in db_type
        enum_values = db_type["enum"]
        assert "postgresql" in enum_values
        assert "mongodb" in enum_values
        assert "mysql" in enum_values
        assert "redis" in enum_values

    def test_connection_name_is_string(self):
        props = _properties(self.tool)
        assert props["connection_name"]["type"] == "string"

    def test_env_prefix_is_string(self):
        props = _properties(self.tool)
        assert props["env_prefix"]["type"] == "string"

    def test_type_is_function(self):
        assert self.tool.get("type") == "function"


# ---------------------------------------------------------------------------
# create_database_schema_tool
# ---------------------------------------------------------------------------


class TestCreateDatabaseSchemaTool:
    def setup_method(self):
        self.tool = create_database_schema_tool()

    def test_returns_dict(self):
        assert isinstance(self.tool, dict)

    def test_name_is_database_schema(self):
        assert _get_func(self.tool)["name"] == "database_schema"

    def test_has_description(self):
        desc = _get_func(self.tool).get("description", "")
        assert len(desc) > 10

    def test_required_connection_name(self):
        assert "connection_name" in _required(self.tool)

    def test_connection_name_property_exists(self):
        props = _properties(self.tool)
        assert "connection_name" in props
        assert props["connection_name"]["type"] == "string"

    def test_exactly_one_property(self):
        assert len(_properties(self.tool)) == 1


# ---------------------------------------------------------------------------
# create_database_query_tool
# ---------------------------------------------------------------------------


class TestCreateDatabaseQueryTool:
    def setup_method(self):
        self.tool = create_database_query_tool()

    def test_returns_dict(self):
        assert isinstance(self.tool, dict)

    def test_name_is_database_query(self):
        assert _get_func(self.tool)["name"] == "database_query"

    def test_has_description(self):
        desc = _get_func(self.tool).get("description", "")
        assert len(desc) > 10

    def test_required_fields(self):
        req = _required(self.tool)
        assert "connection_name" in req
        assert "query" in req
        # limit is optional — not in required
        assert "limit" not in req

    def test_limit_has_default(self):
        props = _properties(self.tool)
        limit = props["limit"]
        assert limit.get("default") == 100

    def test_query_is_string(self):
        props = _properties(self.tool)
        assert props["query"]["type"] == "string"

    def test_connection_name_is_string(self):
        props = _properties(self.tool)
        assert props["connection_name"]["type"] == "string"


# ---------------------------------------------------------------------------
# get_database_tools
# ---------------------------------------------------------------------------


class TestGetDatabaseTools:
    def test_returns_list(self):
        tools = get_database_tools()
        assert isinstance(tools, list)

    def test_returns_three_tools(self):
        tools = get_database_tools()
        assert len(tools) == 3

    def test_contains_all_tool_names(self):
        tools = get_database_tools()
        names = {t["function"]["name"] for t in tools}
        assert names == {"database_connect", "database_schema", "database_query"}

    def test_all_tools_are_dicts(self):
        for tool in get_database_tools():
            assert isinstance(tool, dict)

    def test_order_is_connect_schema_query(self):
        tools = get_database_tools()
        names = [t["function"]["name"] for t in tools]
        assert names == ["database_connect", "database_schema", "database_query"]
