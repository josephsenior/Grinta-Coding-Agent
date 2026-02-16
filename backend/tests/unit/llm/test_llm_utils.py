"""Tests for backend.llm.llm_utils — tool adaptation and token counting."""

import copy
from unittest.mock import MagicMock

from backend.core.config import LLMConfig
from backend.core.message import Message, TextContent
from backend.llm.llm_utils import (
    check_tools,
    _clean_tools_for_gemini,
    _clean_tool_properties,
    get_token_count,
    create_pretrained_tokenizer,
)


class TestCheckTools:
    """Tests for check_tools function."""

    def test_non_gemini_model_unchanged(self):
        """Test non-Gemini models return tools unchanged."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {
                        "properties": {"arg": {"type": "string", "default": "value"}}
                    },
                },
            }
        ]
        config = LLMConfig(model="gpt-4o", api_key="test")
        result = check_tools(tools, config)
        assert result is tools  # Same object

    def test_gemini_model_cleans_tools(self):
        """Test Gemini models clean tools."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {
                        "properties": {
                            "arg": {"type": "string", "default": "value", "format": "uri"}
                        }
                    },
                },
            }
        ]
        config = LLMConfig(model="gemini-1.5-pro", api_key="test")
        result = check_tools(tools, config)
        # Should remove default and unsupported format
        assert "default" not in result[0]["function"]["parameters"]["properties"]["arg"]
        assert "format" not in result[0]["function"]["parameters"]["properties"]["arg"]

    def test_gemini_model_case_insensitive(self):
        """Test Gemini detection is case-insensitive."""
        tools = [
            {
                "function": {
                    "parameters": {"properties": {"x": {"type": "string", "default": "y"}}}
                }
            }
        ]
        config = LLMConfig(model="GEMINI-Pro", api_key="test")
        result = check_tools(tools, config)
        assert "default" not in result[0]["function"]["parameters"]["properties"]["x"]

    def test_openai_model_unchanged(self):
        """Test OpenAI models don't trigger cleaning."""
        tools = [{"function": {"parameters": {"properties": {"x": {"default": "y"}}}}}]
        config = LLMConfig(model="gpt-4-turbo", api_key="test")
        result = check_tools(tools, config)
        assert result is tools

    def test_anthropic_model_unchanged(self):
        """Test Anthropic models don't trigger cleaning."""
        tools = [{"function": {"parameters": {"properties": {"x": {"default": "y"}}}}}]
        config = LLMConfig(model="claude-3-5-sonnet-20241022", api_key="test")
        result = check_tools(tools, config)
        assert result is tools


class TestCleanToolsForGemini:
    """Tests for _clean_tools_for_gemini function."""

    def test_removes_default_values(self):
        """Test removes default from properties."""
        tools = [
            {
                "function": {
                    "parameters": {
                        "properties": {
                            "arg1": {"type": "string", "default": "value1"},
                            "arg2": {"type": "number", "default": 42},
                        }
                    }
                }
            }
        ]
        result = _clean_tools_for_gemini(tools)
        props = result[0]["function"]["parameters"]["properties"]
        assert "default" not in props["arg1"]
        assert "default" not in props["arg2"]

    def test_removes_unsupported_formats(self):
        """Test removes unsupported string formats."""
        tools = [
            {
                "function": {
                    "parameters": {
                        "properties": {
                            "uri_arg": {"type": "string", "format": "uri"},
                            "email_arg": {"type": "string", "format": "email"},
                            "uuid_arg": {"type": "string", "format": "uuid"},
                        }
                    }
                }
            }
        ]
        result = _clean_tools_for_gemini(tools)
        props = result[0]["function"]["parameters"]["properties"]
        assert "format" not in props["uri_arg"]
        assert "format" not in props["email_arg"]
        assert "format" not in props["uuid_arg"]

    def test_keeps_supported_formats(self):
        """Test keeps enum and date-time formats."""
        tools = [
            {
                "function": {
                    "parameters": {
                        "properties": {
                            "enum_arg": {"type": "string", "format": "enum"},
                            "date_arg": {"type": "string", "format": "date-time"},
                        }
                    }
                }
            }
        ]
        result = _clean_tools_for_gemini(tools)
        props = result[0]["function"]["parameters"]["properties"]
        assert props["enum_arg"]["format"] == "enum"
        assert props["date_arg"]["format"] == "date-time"

    def test_non_string_format_unchanged(self):
        """Test non-string types with format are unchanged."""
        tools = [
            {
                "function": {
                    "parameters": {
                        "properties": {"num_arg": {"type": "number", "format": "float"}}
                    }
                }
            }
        ]
        result = _clean_tools_for_gemini(tools)
        # Number format should remain (not a string type)
        props = result[0]["function"]["parameters"]["properties"]
        assert props["num_arg"]["format"] == "float"

    def test_deep_copy(self):
        """Test original tools are not modified."""
        tools = [
            {
                "function": {
                    "parameters": {
                        "properties": {"arg": {"type": "string", "default": "value"}}
                    }
                }
            }
        ]
        original = copy.deepcopy(tools)
        _clean_tools_for_gemini(tools)
        assert tools == original

    def test_multiple_tools(self):
        """Test cleaning multiple tools."""
        tools = [
            {
                "function": {
                    "parameters": {"properties": {"x": {"type": "string", "default": "a"}}}
                }
            },
            {
                "function": {
                    "parameters": {"properties": {"y": {"type": "string", "default": "b"}}}
                }
            },
        ]
        result = _clean_tools_for_gemini(tools)
        assert "default" not in result[0]["function"]["parameters"]["properties"]["x"]
        assert "default" not in result[1]["function"]["parameters"]["properties"]["y"]

    def test_missing_properties(self):
        """Test tools without properties don't crash."""
        tools = [{"function": {"parameters": {}}}]
        result = _clean_tools_for_gemini(tools)
        assert result == tools

    def test_empty_properties(self):
        """Test empty properties dict."""
        tools = [{"function": {"parameters": {"properties": {}}}}]
        result = _clean_tools_for_gemini(tools)
        assert result[0]["function"]["parameters"]["properties"] == {}


class TestCleanToolProperties:
    """Tests for _clean_tool_properties function."""

    def test_removes_defaults_in_place(self):
        """Test removes default values in place."""
        props = {
            "arg1": {"type": "string", "default": "value"},
            "arg2": {"type": "number"},
        }
        _clean_tool_properties(props)
        assert "default" not in props["arg1"]
        assert "arg2" in props

    def test_removes_unsupported_string_formats(self):
        """Test removes unsupported formats from string types."""
        props = {
            "uri": {"type": "string", "format": "uri"},
            "email": {"type": "string", "format": "email"},
        }
        _clean_tool_properties(props)
        assert "format" not in props["uri"]
        assert "format" not in props["email"]

    def test_keeps_enum_format(self):
        """Test keeps enum format."""
        props = {"status": {"type": "string", "format": "enum"}}
        _clean_tool_properties(props)
        assert props["status"]["format"] == "enum"

    def test_keeps_datetime_format(self):
        """Test keeps date-time format."""
        props = {"timestamp": {"type": "string", "format": "date-time"}}
        _clean_tool_properties(props)
        assert props["timestamp"]["format"] == "date-time"

    def test_empty_properties(self):
        """Test with empty properties dict."""
        props = {}
        _clean_tool_properties(props)
        assert props == {}


class TestGetTokenCount:
    """Tests for get_token_count function."""

    def test_message_dict_with_string_content(self):
        """Test token counting with dict messages (string content)."""
        messages = [{"content": "hello world"}]
        count = get_token_count(messages)
        # "hello world" = 11 chars / 4 = 2.75 → 2 tokens
        assert count == 2

    def test_message_object_with_text_content(self):
        """Test token counting with Message objects."""
        messages = [Message(role="user", content=[TextContent(text="test message")])]
        count = get_token_count(messages)
        # "test message" = 12 chars / 4 = 3 tokens
        assert count == 3

    def test_multiple_messages(self):
        """Test token counting with multiple messages."""
        messages = [
            {"content": "first"},  # 5 chars
            {"content": "second"},  # 6 chars
        ]
        count = get_token_count(messages)
        # 11 chars / 4 = 2.75 → 2 tokens
        assert count == 2

    def test_empty_content(self):
        """Test with empty content."""
        messages = [{"content": ""}]
        count = get_token_count(messages)
        assert count == 1  # max(1, 0 / 4)

    def test_list_content(self):
        """Test with list content (TextContent parts)."""
        messages = [
            {
                "content": [
                    {"text": "part1"},
                    {"text": "part2"},
                ]
            }
        ]
        count = get_token_count(messages)
        # "part1part2" = 10 chars / 4 = 2.5 → 2 tokens
        assert count == 2

    def test_minimum_one_token(self):
        """Test minimum count is 1."""
        messages = [{"content": ""}]
        count = get_token_count(messages)
        assert count >= 1

    def test_custom_tokenizer_fallback(self):
        """Test with custom tokenizer (currently ignored)."""
        messages = [{"content": "test"}]
        mock_tokenizer = MagicMock()
        count = get_token_count(messages, custom_tokenizer=mock_tokenizer)
        # Should still use simple estimation
        assert count == 1  # 4 chars / 4 = 1

    def test_model_parameter(self):
        """Test model parameter (currently unused)."""
        messages = [{"content": "test"}]
        count = get_token_count(messages, model="gpt-3.5-turbo")
        assert count == 1

    def test_missing_content(self):
        """Test messages without content attribute."""
        messages = [{"role": "user"}]  # No content
        count = get_token_count(messages)
        assert count == 1

    def test_none_content(self):
        """Test messages with None content."""
        messages = [{"content": None}]
        count = get_token_count(messages)
        # str(None) = "None" = 4 chars / 4 = 1
        assert count == 1


class TestCreatePretrainedTokenizer:
    """Tests for create_pretrained_tokenizer function."""

    def test_returns_name(self):
        """Test returns the name parameter."""
        result = create_pretrained_tokenizer("gpt-4o")
        assert result == "gpt-4o"

    def test_any_string(self):
        """Test works with any string."""
        result = create_pretrained_tokenizer("test-tokenizer")
        assert result == "test-tokenizer"

    def test_empty_string(self):
        """Test with empty string."""
        result = create_pretrained_tokenizer("")
        assert result == ""
