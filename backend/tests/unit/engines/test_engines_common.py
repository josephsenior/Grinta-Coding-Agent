"""Tests for backend.engines.common — pure helper functions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.engines.common import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    extract_assistant_message,
    extract_thought_from_message,
    get_common_path_param,
    get_common_pattern_param,
    get_common_timeout_param,
    parse_tool_call_arguments,
    validate_response_choices,
)


# ── validate_response_choices ────────────────────────────────────────


class TestValidateResponseChoices:
    def test_single_choice(self):
        response = SimpleNamespace(choices=[SimpleNamespace()])
        validate_response_choices(response)  # no error

    def test_zero_choices(self):
        response = SimpleNamespace(choices=[])
        with pytest.raises(AssertionError):
            validate_response_choices(response)

    def test_multiple_choices(self):
        response = SimpleNamespace(choices=[SimpleNamespace(), SimpleNamespace()])
        with pytest.raises(AssertionError):
            validate_response_choices(response)


# ── extract_assistant_message ────────────────────────────────────────


class TestExtractAssistantMessage:
    def test_extracts_message(self):
        msg = SimpleNamespace(content="Hello")
        response = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        assert extract_assistant_message(response) is msg

    def test_missing_message(self):
        response = SimpleNamespace(choices=[SimpleNamespace()])
        with pytest.raises(FunctionCallValidationError, match="missing a message"):
            extract_assistant_message(response)


# ── extract_thought_from_message ─────────────────────────────────────


class TestExtractThoughtFromMessage:
    def test_string_content(self):
        msg = SimpleNamespace(content="Thinking about this...")
        assert extract_thought_from_message(msg) == "Thinking about this..."

    def test_none_content(self):
        msg = SimpleNamespace(content=None)
        assert extract_thought_from_message(msg) == ""

    def test_no_content_attr(self):
        msg = SimpleNamespace()
        assert extract_thought_from_message(msg) == ""

    def test_list_content(self):
        msg = SimpleNamespace(
            content=[
                {"type": "text", "text": "Part 1"},
                {"type": "image"},
                {"type": "text", "text": " Part 2"},
            ]
        )
        assert extract_thought_from_message(msg) == "Part 1 Part 2"

    def test_empty_list(self):
        msg = SimpleNamespace(content=[])
        assert extract_thought_from_message(msg) == ""

    def test_output_text_variant_is_supported(self):
        msg = SimpleNamespace(
            content=[
                {"type": "output_text", "text": "Hello"},
                {"type": "text", "text": " world"},
            ]
        )
        assert extract_thought_from_message(msg) == "Hello world"

    def test_list_of_strings_is_supported(self):
        msg = SimpleNamespace(content=["Part A", " + Part B"])
        assert extract_thought_from_message(msg) == "Part A + Part B"


# ── parse_tool_call_arguments ────────────────────────────────────────


class TestParseToolCallArguments:
    def test_dict_passthrough(self):
        tc = SimpleNamespace(function=SimpleNamespace(arguments={"key": "val"}))
        assert parse_tool_call_arguments(tc) == {"key": "val"}

    def test_json_string(self):
        tc = SimpleNamespace(function=SimpleNamespace(arguments='{"a": 1, "b": "two"}'))
        result = parse_tool_call_arguments(tc)
        assert result == {"a": 1, "b": "two"}

    def test_invalid_json(self):
        tc = SimpleNamespace(function=SimpleNamespace(arguments="not-json"))
        with pytest.raises(FunctionCallValidationError, match="Failed to parse"):
            parse_tool_call_arguments(tc)

    def test_missing_attribute(self):
        tc = SimpleNamespace()
        # AttributeError accessing function.arguments happens in error msg too,
        # so it propagates as raw AttributeError rather than wrapped
        with pytest.raises(AttributeError):
            parse_tool_call_arguments(tc)


# ── Exception hierarchy ──────────────────────────────────────────────


class TestExceptionHierarchy:
    def test_validation_error_is_exception(self):
        assert issubclass(FunctionCallValidationError, Exception)

    def test_not_exists_is_validation_error(self):
        assert issubclass(FunctionCallNotExistsError, FunctionCallValidationError)


# ── Common parameter helpers ─────────────────────────────────────────


class TestCommonParamHelpers:
    def test_path_param_default(self):
        p = get_common_path_param()
        assert p["type"] == "string"
        assert "path" in p["description"].lower()

    def test_path_param_custom(self):
        p = get_common_path_param("Custom description")
        assert p["description"] == "Custom description"

    def test_pattern_param(self):
        p = get_common_pattern_param("A glob pattern")
        assert p["type"] == "string"
        assert p["description"] == "A glob pattern"

    def test_timeout_param_default(self):
        p = get_common_timeout_param()
        assert p["type"] == "number"
        assert "timeout" in p["description"].lower()

    def test_timeout_param_custom(self):
        p = get_common_timeout_param("Max wait time")
        assert p["description"] == "Max wait time"
