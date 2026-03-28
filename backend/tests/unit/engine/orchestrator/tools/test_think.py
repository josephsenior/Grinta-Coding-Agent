"""Tests for backend.engine.tools.think — lightweight reasoning tool."""

from backend.engine.tools.think import create_think_tool


class TestCreateThinkTool:
    """Tests for create_think_tool function."""

    def test_create_think_tool_returns_dict(self):
        """Test create_think_tool returns a dictionary."""
        tool = create_think_tool()
        assert isinstance(tool, dict)

    def test_tool_has_correct_type(self):
        """Test tool has type 'function'."""
        tool = create_think_tool()
        assert tool.get("type") == "function"

    def test_tool_has_function_field(self):
        """Test tool has 'function' field."""
        tool = create_think_tool()
        assert "function" in tool

    def test_function_name_is_think(self):
        """Test function name is 'think'."""
        tool = create_think_tool()
        function = tool.get("function", {})
        assert function.get("name") == "think"

    def test_function_has_description(self):
        """Test function has description."""
        tool = create_think_tool()
        function = tool.get("function", {})
        description = function.get("description", "")
        assert description
        assert "think" in description.lower()

    def test_description_mentions_brainstorming(self):
        """Test description mentions brainstorming use case."""
        tool = create_think_tool()
        function = tool.get("function", {})
        description = function.get("description", "")
        assert "brainstorm" in description.lower()

    def test_description_mentions_logging(self):
        """Test description mentions logging thoughts."""
        tool = create_think_tool()
        function = tool.get("function", {})
        description = function.get("description", "")
        assert "log" in description.lower()

    def test_function_has_parameters(self):
        """Test function has parameters field."""
        tool = create_think_tool()
        function = tool.get("function", {})
        assert "parameters" in function

    def test_parameters_has_properties(self):
        """Test parameters has properties."""
        tool = create_think_tool()
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        assert "properties" in parameters

    def test_thought_parameter_exists(self):
        """Test thought parameter is defined."""
        tool = create_think_tool()
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})
        assert "thought" in properties

    def test_thought_parameter_is_string(self):
        """Test thought parameter is of type string."""
        tool = create_think_tool()
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})
        thought = properties.get("thought", {})
        assert thought.get("type") == "string"

    def test_thought_parameter_has_description(self):
        """Test thought parameter has description."""
        tool = create_think_tool()
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})
        thought = properties.get("thought", {})
        assert "description" in thought
        assert len(thought.get("description", "")) > 0

    def test_thought_is_required(self):
        """Test thought parameter is required."""
        tool = create_think_tool()
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        required = parameters.get("required", [])
        assert "thought" in required

    def test_only_one_required_parameter(self):
        """Test only one parameter is required."""
        tool = create_think_tool()
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        required = parameters.get("required", [])
        assert len(required) == 1

    def test_tool_structure_valid(self):
        """Test overall tool structure is valid."""
        tool = create_think_tool()
        assert "type" in tool
        assert "function" in tool
        function = tool["function"]
        assert "name" in function
        assert "description" in function
        assert "parameters" in function
