"""Tests for backend.llm.fn_call_converter — core conversion utilities."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from backend.core.exceptions import (
    FunctionCallConversionError,
    FunctionCallValidationError,
)
from backend.llm.fn_call_converter import (
    ExampleStepBuilder,
    FN_PARAM_REGEX_PATTERN,
    FN_REGEX_PATTERN,
    STOP_WORDS,
    TOOL_RESULT_REGEX_PATTERN,
    _convert_parameter_value,
    _convert_to_array,
    _convert_to_integer,
    _extract_parameter_schema,
    _fix_stopword,
    _format_parameter,
    _format_tool_call_string,
    _normalize_parameter_tags,
    _parse_tool_call_arguments,
    _validate_enum_constraint,
    _validate_parameter_allowed,
    _validate_required_parameters,
    _validate_tool_call_structure,
    convert_from_multiple_tool_calls_to_single_tool_call_messages,
    convert_fncall_messages_to_non_fncall_messages,
    convert_tool_call_to_string,
    convert_tools_to_description,
    refine_prompt,
)


# ── refine_prompt ──────────────────────────────────────────────────────

class TestRefinePrompt:
    def test_non_windows(self):
        with patch.object(sys, "platform", "linux"):
            assert refine_prompt("run bash command") == "run bash command"

    def test_windows_replaces_bash(self):
        with patch.object(sys, "platform", "win32"):
            assert refine_prompt("run bash command") == "run powershell command"

    def test_no_bash_unchanged(self):
        with patch.object(sys, "platform", "win32"):
            assert refine_prompt("run shell") == "run shell"


# ── _validate_tool_call_structure ──────────────────────────────────────

class TestValidateToolCallStructure:
    def test_valid(self):
        tc = {"function": {"name": "f"}, "id": "1", "type": "function"}
        _validate_tool_call_structure(tc)  # no error

    def test_missing_function(self):
        with pytest.raises(FunctionCallConversionError, match="function"):
            _validate_tool_call_structure({"id": "1", "type": "function"})

    def test_missing_id(self):
        with pytest.raises(FunctionCallConversionError, match="id"):
            _validate_tool_call_structure({"function": {}, "type": "function"})

    def test_missing_type(self):
        with pytest.raises(FunctionCallConversionError, match="type"):
            _validate_tool_call_structure({"function": {}, "id": "1"})

    def test_wrong_type(self):
        with pytest.raises(FunctionCallConversionError, match="function"):
            _validate_tool_call_structure({"function": {}, "id": "1", "type": "tool"})


# ── _parse_tool_call_arguments ─────────────────────────────────────────

class TestParseToolCallArguments:
    def test_valid_json(self):
        tc = {"function": {"arguments": '{"key": "val"}'}}
        assert _parse_tool_call_arguments(tc) == {"key": "val"}

    def test_invalid_json(self):
        tc = {"function": {"arguments": "not json"}}
        with pytest.raises(FunctionCallConversionError, match="JSON"):
            _parse_tool_call_arguments(tc)


# ── _format_parameter ─────────────────────────────────────────────────

class TestFormatParameter:
    def test_simple_string(self):
        result = _format_parameter("name", "value")
        assert "<parameter=name>value</parameter>" in result

    def test_multiline_string(self):
        result = _format_parameter("code", "line1\nline2")
        assert "<parameter=code>\nline1\nline2\n</parameter>" in result

    def test_list_value(self):
        result = _format_parameter("items", [1, 2, 3])
        assert json.dumps([1, 2, 3]) in result

    def test_dict_value(self):
        result = _format_parameter("data", {"a": 1})
        assert json.dumps({"a": 1}) in result

    def test_integer_value(self):
        result = _format_parameter("count", 42)
        assert "42" in result


# ── _format_tool_call_string ──────────────────────────────────────────

class TestFormatToolCallString:
    def test_basic(self):
        result = _format_tool_call_string("test_fn", {"x": "1", "y": "2"})
        assert "<function=test_fn>" in result
        assert "</function>" in result
        assert "<parameter=x>1</parameter>" in result
        assert "<parameter=y>2</parameter>" in result

    def test_empty_args(self):
        result = _format_tool_call_string("empty", {})
        assert "<function=empty>" in result
        assert "</function>" in result


# ── convert_tool_call_to_string ────────────────────────────────────────

class TestConvertToolCallToString:
    def test_basic(self):
        tc = {
            "function": {"name": "my_fn", "arguments": '{"cmd": "ls"}'},
            "id": "1",
            "type": "function",
        }
        result = convert_tool_call_to_string(tc)
        assert "<function=my_fn>" in result
        assert "<parameter=cmd>ls</parameter>" in result

    def test_invalid_structure(self):
        with pytest.raises(FunctionCallConversionError):
            convert_tool_call_to_string({"id": "1"})


# ── convert_tools_to_description ───────────────────────────────────────

class TestConvertToolsToDescription:
    def test_basic(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "my_tool",
                    "description": "Does stuff",
                    "parameters": {
                        "properties": {"x": {"type": "string", "description": "input"}},
                        "required": ["x"],
                    },
                },
            }
        ]
        result = convert_tools_to_description(tools)
        assert "my_tool" in result
        assert "Does stuff" in result
        assert "(1) x (string, required)" in result

    def test_no_params(self):
        tools = [{"type": "function", "function": {"name": "t", "description": "d"}}]
        result = convert_tools_to_description(tools)
        assert "No parameters" in result

    def test_optional_param(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "t",
                    "description": "d",
                    "parameters": {
                        "properties": {"opt": {"type": "integer", "description": "o"}},
                        "required": [],
                    },
                },
            }
        ]
        result = convert_tools_to_description(tools)
        assert "optional" in result

    def test_enum_values(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "t",
                    "description": "d",
                    "parameters": {
                        "properties": {
                            "mode": {
                                "type": "string",
                                "description": "m",
                                "enum": ["a", "b"],
                            }
                        },
                        "required": [],
                    },
                },
            }
        ]
        result = convert_tools_to_description(tools)
        assert "`a`" in result
        assert "`b`" in result

    def test_multiple_tools(self):
        tools = [
            {"type": "function", "function": {"name": "t1", "description": "d1"}},
            {"type": "function", "function": {"name": "t2", "description": "d2"}},
        ]
        result = convert_tools_to_description(tools)
        assert "#1" in result
        assert "#2" in result


# ── _fix_stopword ──────────────────────────────────────────────────────

class TestFixStopword:
    def test_adds_closing_when_missing(self):
        s = "<function=foo>\n<parameter=x>1</parameter>"
        result = _fix_stopword(s)
        assert result.endswith("\n</function>")

    def test_ends_with_partial_closing(self):
        s = "<function=foo>\n<parameter=x>1</parameter>\n</"
        result = _fix_stopword(s)
        assert result.endswith("</function>")

    def test_no_function_tag_unchanged(self):
        s = "just plain text"
        assert _fix_stopword(s) == s

    def test_multiple_function_tags_unchanged(self):
        s = "<function=a>\n</function>\n<function=b>\n</function>"
        assert _fix_stopword(s) == s


# ── _normalize_parameter_tags ──────────────────────────────────────────

class TestNormalizeParameterTags:
    def test_malformed_tag(self):
        body = "<parameter=name=value</parameter>"
        result = _normalize_parameter_tags(body)
        assert result == "<parameter=name>value</parameter>"

    def test_already_correct(self):
        body = "<parameter=name>value</parameter>"
        assert _normalize_parameter_tags(body) == body

    def test_multiple_malformed(self):
        body = "<parameter=a=1</parameter>\n<parameter=b=2</parameter>"
        result = _normalize_parameter_tags(body)
        assert "<parameter=a>1</parameter>" in result
        assert "<parameter=b>2</parameter>" in result


# ── _convert_to_integer / _convert_to_array ────────────────────────────

class TestTypeConverters:
    def test_convert_to_integer_valid(self):
        assert _convert_to_integer("count", "42") == 42

    def test_convert_to_integer_invalid(self):
        with pytest.raises(FunctionCallValidationError, match="integer"):
            _convert_to_integer("count", "abc")

    def test_convert_to_array_valid(self):
        assert _convert_to_array("items", '[1, 2, 3]') == [1, 2, 3]

    def test_convert_to_array_invalid(self):
        with pytest.raises(FunctionCallValidationError, match="array"):
            _convert_to_array("items", "not json")


# ── _validate_parameter_allowed ────────────────────────────────────────

class TestValidateParameterAllowed:
    def test_allowed(self):
        _validate_parameter_allowed("x", {"x", "y"}, "fn")  # no error

    def test_not_allowed(self):
        with pytest.raises(FunctionCallValidationError, match="not allowed"):
            _validate_parameter_allowed("z", {"x", "y"}, "fn")

    def test_empty_allowed_always_ok(self):
        _validate_parameter_allowed("anything", set(), "fn")  # no error


# ── _validate_required_parameters ──────────────────────────────────────

class TestValidateRequiredParameters:
    def test_all_present(self):
        _validate_required_parameters({"a", "b"}, {"a", "b"}, "fn")  # no error

    def test_missing(self):
        with pytest.raises(FunctionCallValidationError, match="Missing"):
            _validate_required_parameters({"a"}, {"a", "b"}, "fn")


# ── _validate_enum_constraint ──────────────────────────────────────────

class TestValidateEnumConstraint:
    def test_valid_enum(self):
        tool = {"parameters": {"properties": {"mode": {"enum": ["a", "b"]}}}}
        _validate_enum_constraint("mode", "a", tool, "fn")  # no error

    def test_invalid_enum(self):
        tool = {"parameters": {"properties": {"mode": {"enum": ["a", "b"]}}}}
        with pytest.raises(FunctionCallValidationError, match="one of"):
            _validate_enum_constraint("mode", "c", tool, "fn")

    def test_no_enum(self):
        tool = {"parameters": {"properties": {"mode": {"type": "string"}}}}
        _validate_enum_constraint("mode", "anything", tool, "fn")  # no error

    def test_no_parameters(self):
        _validate_enum_constraint("mode", "x", {}, "fn")  # no error


# ── _extract_parameter_schema ──────────────────────────────────────────

class TestExtractParameterSchema:
    def test_full_schema(self):
        tool = {
            "parameters": {
                "required": ["x"],
                "properties": {
                    "x": {"type": "string"},
                    "y": {"type": "integer"},
                },
            }
        }
        result = _extract_parameter_schema(tool)
        assert result["required_params"] == {"x"}
        assert result["allowed_params"] == {"x", "y"}
        assert result["param_name_to_type"]["x"] == "string"

    def test_no_parameters(self):
        result = _extract_parameter_schema({})
        assert result["required_params"] == set()
        assert result["allowed_params"] == set()


# ── _convert_parameter_value ───────────────────────────────────────────

class TestConvertParameterValue:
    def test_string_passthrough(self):
        assert _convert_parameter_value("x", "hello", {"x": "string"}) == "hello"

    def test_integer_conversion(self):
        assert _convert_parameter_value("x", "42", {"x": "integer"}) == 42

    def test_array_conversion(self):
        assert _convert_parameter_value("x", "[1,2]", {"x": "array"}) == [1, 2]

    def test_unknown_param(self):
        assert _convert_parameter_value("z", "val", {"x": "string"}) == "val"


# ── ExampleStepBuilder ─────────────────────────────────────────────────

class TestExampleStepBuilder:
    def test_empty_tools(self):
        builder = ExampleStepBuilder(set())
        assert builder.build_all_steps() == ""

    def test_with_execute_bash(self):
        builder = ExampleStepBuilder({"execute_bash"})
        result = builder.build_all_steps()
        assert "execute_bash" in result

    def test_with_finish(self):
        builder = ExampleStepBuilder({"finish"})
        result = builder.build_all_steps()
        assert "finish" in result

    def test_str_replace_editor(self):
        builder = ExampleStepBuilder({"str_replace_editor"})
        result = builder.build_all_steps()
        assert "str_replace_editor" in result

    def test_edit_file_fallback(self):
        builder = ExampleStepBuilder({"edit_file"})
        result = builder.build_all_steps()
        assert "edit_file" in result


# ── convert_fncall_messages_to_non_fncall_messages ─────────────────────

class TestConvertFncallToNonFncall:
    def _make_tool(self, name="my_fn"):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": "test",
                "parameters": {
                    "properties": {"cmd": {"type": "string", "description": "c"}},
                    "required": ["cmd"],
                },
            },
        }

    def test_system_message_gets_suffix(self):
        tools = [self._make_tool()]
        messages = [{"role": "system", "content": "You are helpful"}]
        result = convert_fncall_messages_to_non_fncall_messages(messages, tools)
        assert "You have access to the following functions" in result[0]["content"]

    def test_user_message_preserved(self):
        tools = [self._make_tool()]
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Hello"},
        ]
        result = convert_fncall_messages_to_non_fncall_messages(
            messages, tools, add_in_context_learning_example=False
        )
        assert result[1]["role"] == "user"

    def test_tool_message_converted_to_user(self):
        tools = [self._make_tool()]
        messages = [
            {"role": "tool", "name": "my_fn", "content": "result here"},
        ]
        result = convert_fncall_messages_to_non_fncall_messages(
            messages, tools, add_in_context_learning_example=False
        )
        assert result[0]["role"] == "user"
        assert "EXECUTION RESULT" in result[0]["content"][0]["text"]


# ── convert_from_multiple_tool_calls_to_single_tool_call_messages ──────

class TestConvertMultipleToSingle:
    def test_single_tool_call_passthrough(self):
        messages = [
            {
                "role": "assistant",
                "content": "thinking",
                "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "done"},
        ]
        result = convert_from_multiple_tool_calls_to_single_tool_call_messages(messages)
        assert len(result) == 2

    def test_multiple_tool_calls_split(self):
        messages = [
            {
                "role": "assistant",
                "content": "doing both",
                "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "f1", "arguments": "{}"}},
                    {"id": "t2", "type": "function", "function": {"name": "f2", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "r1"},
            {"role": "tool", "tool_call_id": "t2", "content": "r2"},
        ]
        result = convert_from_multiple_tool_calls_to_single_tool_call_messages(messages)
        # Should have: assistant(t1), tool(t1), assistant(t2), tool(t2)
        assert len(result) == 4

    def test_pending_raises_if_not_ignored(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "f1", "arguments": "{}"}},
                    {"id": "t2", "type": "function", "function": {"name": "f2", "arguments": "{}"}},
                ],
            },
        ]
        with pytest.raises(FunctionCallConversionError, match="pending"):
            convert_from_multiple_tool_calls_to_single_tool_call_messages(messages)

    def test_pending_ignored_when_flag_set(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "f1", "arguments": "{}"}},
                    {"id": "t2", "type": "function", "function": {"name": "f2", "arguments": "{}"}},
                ],
            },
        ]
        result = convert_from_multiple_tool_calls_to_single_tool_call_messages(
            messages, ignore_final_tool_result=True
        )
        assert isinstance(result, list)


# ── Regex patterns ─────────────────────────────────────────────────────

class TestRegexPatterns:
    def test_fn_regex_matches(self):
        import re
        text = "<function=my_fn>\n<parameter=x>1</parameter>\n</function>"
        match = re.search(FN_REGEX_PATTERN, text, re.DOTALL)
        assert match is not None
        assert match.group(1) == "my_fn"

    def test_fn_param_regex(self):
        import re
        text = "<parameter=name>value</parameter>"
        match = re.search(FN_PARAM_REGEX_PATTERN, text, re.DOTALL)
        assert match is not None
        assert match.group(1) == "name"
        assert match.group(2) == "value"

    def test_tool_result_regex(self):
        import re
        text = "EXECUTION RESULT of [my_tool]:\nsome output"
        match = re.search(TOOL_RESULT_REGEX_PATTERN, text, re.DOTALL)
        assert match is not None
        assert match.group(1) == "my_tool"

    def test_stop_words(self):
        assert "</function" in STOP_WORDS
