"""Tests for MCPClientTool proxy model."""

import unittest

from backend.mcp.tool import MCPClientTool


class TestMCPClientTool(unittest.TestCase):
    """Tests for MCPClientTool - client-side tool proxy."""

    def test_creation(self) -> None:
        """Test creating MCPClientTool instance."""
        tool = MCPClientTool(
            name="search_files",
            description="Search for files by name pattern",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["pattern"],
            },
        )

        self.assertEqual(tool.name, "search_files")
        self.assertEqual(tool.description, "Search for files by name pattern")
        self.assertIn("properties", tool.inputSchema)

    def test_to_param_converts_to_function_call_format(self) -> None:
        """Test to_param() returns OpenAI function call format."""
        tool = MCPClientTool(
            name="read_file",
            description="Read file contents",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )

        param = tool.to_param()

        self.assertEqual(param["type"], "function")
        self.assertEqual(param["function"]["name"], "read_file")
        self.assertEqual(param["function"]["description"], "Read file contents")
        self.assertIn("properties", param["function"]["parameters"])
        self.assertIn("path", param["function"]["parameters"]["properties"])

    def test_to_param_preserves_schema_structure(self) -> None:
        """Test to_param preserves full inputSchema structure."""
        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                    "minLength": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
                "fuzzy": {
                    "type": "boolean",
                    "description": "Enable fuzzy matching",
                    "default": True,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

        tool = MCPClientTool(
            name="search_components",
            description="Fuzzy search components",
            inputSchema=schema,
        )

        param = tool.to_param()
        function_params = param["function"]["parameters"]

        self.assertEqual(function_params["type"], "object")
        self.assertIn("query", function_params["properties"])
        self.assertIn("limit", function_params["properties"])
        self.assertIn("fuzzy", function_params["properties"])
        self.assertEqual(function_params["required"], ["query"])
        self.assertEqual(function_params["properties"]["limit"]["minimum"], 1)
        self.assertEqual(function_params["properties"]["limit"]["maximum"], 100)

    def test_to_param_with_complex_nested_schema(self) -> None:
        """Test to_param handles nested object schemas."""
        schema = {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["active", "archived"]},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        }

        tool = MCPClientTool(
            name="filter_items",
            description="Filter items",
            inputSchema=schema,
        )

        param = tool.to_param()
        filters_prop = param["function"]["parameters"]["properties"]["filters"]

        self.assertEqual(filters_prop["type"], "object")
        self.assertIn("status", filters_prop["properties"])
        self.assertIn("tags", filters_prop["properties"])
        self.assertEqual(filters_prop["properties"]["tags"]["type"], "array")

    def test_to_param_with_empty_schema(self) -> None:
        """Test to_param with minimal schema."""
        tool = MCPClientTool(
            name="ping",
            description="Simple ping",
            inputSchema={"type": "object"},
        )

        param = tool.to_param()

        self.assertEqual(param["type"], "function")
        self.assertEqual(param["function"]["name"], "ping")
        self.assertEqual(param["function"]["parameters"]["type"], "object")

    def test_arbitrary_types_allowed(self) -> None:
        """Test model_config allows arbitrary types."""
        # This tests that Pydantic config is set correctly
        tool = MCPClientTool(
            name="test_tool",
            description="Test",
            inputSchema={},
        )

        # Should not raise validation error
        self.assertIsNotNone(tool)

    def test_multiple_tools_independent(self) -> None:
        """Test multiple tool instances are independent."""
        tool1 = MCPClientTool(
            name="tool1",
            description="First tool",
            inputSchema={"type": "object"},
        )
        tool2 = MCPClientTool(
            name="tool2",
            description="Second tool",
            inputSchema={"type": "object"},
        )

        param1 = tool1.to_param()
        param2 = tool2.to_param()

        self.assertNotEqual(param1["function"]["name"], param2["function"]["name"])
        self.assertNotEqual(
            param1["function"]["description"], param2["function"]["description"]
        )


if __name__ == "__main__":
    unittest.main()
