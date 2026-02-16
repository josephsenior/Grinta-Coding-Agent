"""Tests for backend.llm.llm_utils — check_tools, _clean_tools_for_gemini, get_token_count."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.llm.llm_utils import (
    _clean_tool_properties,
    _clean_tools_for_gemini,
    check_tools,
    get_token_count,
)


def _make_llm_config(model: str) -> MagicMock:
    cfg = MagicMock()
    cfg.model = model
    return cfg


def _make_tools_with_format():
    return [
        {
            "type": "function",
            "function": {
                "name": "test",
                "parameters": {
                    "properties": {
                        "name": {"type": "string", "default": "world"},
                        "style": {"type": "string", "format": "uri"},
                        "when": {"type": "string", "format": "date-time"},
                    }
                },
            },
        }
    ]


# ── check_tools ────────────────────────────────────────────────────────

class TestCheckTools:
    def test_non_gemini_passthrough(self):
        tools = [{"type": "function", "function": {"name": "t"}}]
        result = check_tools(tools, _make_llm_config("gpt-4"))
        assert result is tools  # same object, no copy

    def test_gemini_triggers_cleaning(self):
        tools = _make_tools_with_format()
        result = check_tools(tools, _make_llm_config("gemini-pro"))
        # Should have removed `default` and unsupported `format`
        props = result[0]["function"]["parameters"]["properties"]
        assert "default" not in props["name"]
        assert "format" not in props["style"]  # uri is unsupported
        assert props["when"]["format"] == "date-time"  # supported, kept

    def test_gemini_case_insensitive(self):
        tools = _make_tools_with_format()
        result = check_tools(tools, _make_llm_config("Gemini-1.5-Pro"))
        props = result[0]["function"]["parameters"]["properties"]
        assert "default" not in props["name"]


# ── _clean_tools_for_gemini ────────────────────────────────────────────

class TestCleanToolsForGemini:
    def test_deep_copy(self):
        original = _make_tools_with_format()
        cleaned = _clean_tools_for_gemini(original)
        # Original should be unchanged
        assert "default" in original[0]["function"]["parameters"]["properties"]["name"]
        assert "default" not in cleaned[0]["function"]["parameters"]["properties"]["name"]

    def test_tool_without_parameters(self):
        tools = [{"type": "function", "function": {"name": "t"}}]
        result = _clean_tools_for_gemini(tools)
        assert result[0]["function"]["name"] == "t"

    def test_tool_without_properties(self):
        tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
        result = _clean_tools_for_gemini(tools)
        assert result[0]["function"]["name"] == "t"


# ── _clean_tool_properties ─────────────────────────────────────────────

class TestCleanToolProperties:
    def test_removes_default(self):
        props = {"x": {"type": "string", "default": "hello"}}
        _clean_tool_properties(props)
        assert "default" not in props["x"]

    def test_removes_unsupported_format(self):
        props = {"x": {"type": "string", "format": "uri"}}
        _clean_tool_properties(props)
        assert "format" not in props["x"]

    def test_keeps_enum_format(self):
        props = {"x": {"type": "string", "format": "enum"}}
        _clean_tool_properties(props)
        assert props["x"]["format"] == "enum"

    def test_keeps_datetime_format(self):
        props = {"x": {"type": "string", "format": "date-time"}}
        _clean_tool_properties(props)
        assert props["x"]["format"] == "date-time"

    def test_non_string_type_keeps_format(self):
        props = {"x": {"type": "integer", "format": "int32"}}
        _clean_tool_properties(props)
        assert props["x"]["format"] == "int32"


# ── get_token_count ────────────────────────────────────────────────────

class TestGetTokenCount:
    def test_simple_string(self):
        msgs = [{"content": "hello world"}]
        count = get_token_count(msgs)
        assert count == max(1, len("hello world") // 4)

    def test_empty_messages(self):
        assert get_token_count([]) == 1  # min 1

    def test_list_content(self):
        msgs = [{"content": [{"type": "text", "text": "hello"}]}]
        count = get_token_count(msgs)
        assert count >= 1

    def test_multiple_messages(self):
        msgs = [
            {"content": "a" * 100},
            {"content": "b" * 200},
        ]
        count = get_token_count(msgs)
        assert count == max(1, 300 // 4)

    def test_message_objects(self):
        msg = MagicMock()
        msg.content = "test message"
        count = get_token_count([msg])
        assert count >= 1

    def test_none_content(self):
        msgs = [{"content": None}]
        count = get_token_count(msgs)
        assert count >= 1
