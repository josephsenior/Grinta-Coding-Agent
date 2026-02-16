"""Unit tests for backend.controller.agent_tools — tool construction helpers."""

from __future__ import annotations

import pytest

from backend.controller.agent_tools import (
    attach_additional_fields,
    build_tool,
    chunk_args_from_payload,
)


# ---------------------------------------------------------------------------
# chunk_args_from_payload
# ---------------------------------------------------------------------------


class TestChunkArgsFromPayload:
    def test_valid_full(self):
        payload = {
            "name": "run_cmd",
            "description": "Run a command",
            "parameters": {"type": "object"},
            "strict": True,
        }
        args = chunk_args_from_payload(payload, {})
        assert args is not None
        assert args["name"] == "run_cmd"
        assert args["description"] == "Run a command"
        assert args["parameters"] == {"type": "object"}
        assert args["strict"] is True

    def test_name_only(self):
        payload = {"name": "simple"}
        args = chunk_args_from_payload(payload, {})
        assert args is not None
        assert args["name"] == "simple"
        assert "description" not in args
        assert "parameters" not in args

    def test_no_name(self):
        payload = {"description": "no name"}
        result = chunk_args_from_payload(payload, {})
        assert result is None

    def test_empty_name(self):
        payload = {"name": ""}
        result = chunk_args_from_payload(payload, {})
        assert result is None

    def test_non_string_name(self):
        payload = {"name": 123}
        result = chunk_args_from_payload(payload, {})
        assert result is None

    def test_non_dict_parameters_ignored(self):
        payload = {"name": "x", "parameters": "not a dict"}
        args = chunk_args_from_payload(payload, {})
        assert args is not None
        assert "parameters" not in args

    def test_non_bool_strict_ignored(self):
        payload = {"name": "x", "strict": "yes"}
        args = chunk_args_from_payload(payload, {})
        assert args is not None
        assert "strict" not in args

    def test_non_string_description_ignored(self):
        payload = {"name": "x", "description": 42}
        args = chunk_args_from_payload(payload, {})
        assert args is not None
        assert "description" not in args


# ---------------------------------------------------------------------------
# attach_additional_fields
# ---------------------------------------------------------------------------


class _Bag:
    """Simple object that supports setattr."""
    pass


class TestAttachAdditionalFields:
    def test_extra_fields(self):
        tool_param = _Bag()
        normalized = {"type": "function", "function": {}, "custom_key": "value"}
        attach_additional_fields(tool_param, normalized)
        assert tool_param.custom_key == "value"  # type: ignore[attr-defined]

    def test_skips_type_and_function(self):
        tool_param = _Bag()
        normalized = {"type": "function", "function": {"name": "x"}}
        attach_additional_fields(tool_param, normalized)
        # No extra attributes should be set
        assert not hasattr(tool_param, "type")
        assert not hasattr(tool_param, "function")


# ---------------------------------------------------------------------------
# build_tool
# ---------------------------------------------------------------------------


class TestBuildTool:
    def test_no_function_payload(self):
        result = build_tool({"type": "function"})
        assert result is None

    def test_non_dict_function(self):
        result = build_tool({"type": "function", "function": "not_a_dict"})
        assert result is None

    def test_valid_tool(self):
        tool = {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                },
            },
        }
        result = build_tool(tool)
        assert result is not None

    def test_missing_function_name(self):
        tool = {
            "type": "function",
            "function": {"description": "no name"},
        }
        result = build_tool(tool)
        assert result is None
