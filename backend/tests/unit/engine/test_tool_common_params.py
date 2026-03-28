"""Tests for backend.engine.tools.common — tool parameter factories."""

from __future__ import annotations

from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_is_input_param,
    get_path_param,
    get_security_risk_param,
    get_timeout_param,
    get_url_param,
)


class TestCreateToolDefinition:
    def test_basic(self):
        result = create_tool_definition(
            name="my_tool",
            description="does stuff",
            properties={"x": {"type": "string", "description": "input"}},
            required=["x"],
        )
        assert result["type"] == "function"
        assert result["function"]["name"] == "my_tool"
        assert result["function"]["description"] == "does stuff"
        params = result["function"]["parameters"]
        assert params["type"] == "object"
        assert "x" in params["properties"]
        assert params["required"] == ["x"]
        assert params["additionalProperties"] is False

    def test_additional_properties_true(self):
        result = create_tool_definition(
            name="t",
            description="d",
            properties={},
            required=[],
            additional_properties=True,
        )
        assert result["function"]["parameters"]["additionalProperties"] is True


class TestGetIsInputParam:
    def test_default(self):
        p = get_is_input_param()
        assert p["type"] == "string"
        assert p["enum"] == ["true", "false"]
        assert "input" in p["description"].lower()

    def test_custom_description(self):
        p = get_is_input_param("Custom desc")
        assert p["description"] == "Custom desc"


class TestGetSecurityRiskParam:
    def test_structure(self):
        p = get_security_risk_param()
        assert p["type"] == "string"
        assert "enum" in p
        assert isinstance(p["enum"], list)
        assert "description" in p


class TestGetCommandParam:
    def test_basic(self):
        p = get_command_param("Run a command")
        assert p["type"] == "string"
        assert p["description"] == "Run a command"
        assert "enum" not in p

    def test_with_enum(self):
        p = get_command_param("Pick one", enum=["a", "b"])
        assert p["enum"] == ["a", "b"]


class TestGetUrlParam:
    def test_default(self):
        p = get_url_param()
        assert p["type"] == "string"
        assert "URL" in p["description"]

    def test_custom(self):
        p = get_url_param("Navigate here")
        assert p["description"] == "Navigate here"


class TestGetPathParam:
    def test_basic(self):
        p = get_path_param("File path")
        assert p["type"] == "string"
        assert p["description"] == "File path"


class TestGetTimeoutParam:
    def test_basic(self):
        p = get_timeout_param("Max wait time")
        assert p["type"] == "number"
        assert p["description"] == "Max wait time"
