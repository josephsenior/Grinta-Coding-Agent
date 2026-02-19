"""Tests for backend.llm.tool_types — make_function_chunk, make_tool_param, PromptTokensDetails."""

from __future__ import annotations

import pytest

from backend.llm.tool_types import (
    PromptTokensDetails,
    make_function_chunk,
    make_tool_param,
)


# ── make_function_chunk ────────────────────────────────────────────────


class TestMakeFunctionChunk:
    def test_basic(self):
        chunk = make_function_chunk(name="my_func", description="does stuff")
        assert chunk["name"] == "my_func"
        assert chunk["description"] == "does stuff"

    def test_attribute_access(self):
        chunk = make_function_chunk(name="f", description="d")
        assert chunk.name == "f"
        assert chunk.description == "d"

    def test_parameters(self):
        params = {"type": "object", "properties": {"x": {"type": "string"}}}
        chunk = make_function_chunk(name="f", parameters=params)
        assert chunk["parameters"] == params

    def test_missing_attr_raises(self):
        chunk = make_function_chunk(name="f")
        with pytest.raises(AttributeError):
            _ = chunk.nonexistent

    def test_setattr(self):
        chunk = make_function_chunk(name="f")
        chunk.new_field = "value"
        assert chunk["new_field"] == "value"
        assert chunk.new_field == "value"

    def test_is_dict(self):
        chunk = make_function_chunk(name="f")
        assert isinstance(chunk, dict)

    def test_strict_field(self):
        chunk = make_function_chunk(name="f", strict=True)
        assert chunk.strict is True


# ── make_tool_param ────────────────────────────────────────────────────


class TestMakeToolParam:
    def test_basic(self):
        fn = make_function_chunk(name="f", description="d")
        tool = make_tool_param(function=fn)
        assert tool["type"] == "function"
        assert tool["function"] is fn

    def test_attribute_access(self):
        fn = make_function_chunk(name="f")
        tool = make_tool_param(function=fn)
        assert tool.type == "function"
        assert tool.function is fn

    def test_custom_type(self):
        fn = make_function_chunk(name="f")
        tool = make_tool_param(function=fn, type="custom")
        assert tool["type"] == "custom"

    def test_extras(self):
        fn = make_function_chunk(name="f")
        tool = make_tool_param(function=fn, extra_field="hello")
        assert tool["extra_field"] == "hello"

    def test_is_dict(self):
        fn = make_function_chunk(name="f")
        tool = make_tool_param(function=fn)
        assert isinstance(tool, dict)

    def test_missing_attr_raises(self):
        fn = make_function_chunk(name="f")
        tool = make_tool_param(function=fn)
        with pytest.raises(AttributeError):
            _ = tool.nonexistent


# ── PromptTokensDetails ───────────────────────────────────────────────


class TestPromptTokensDetails:
    def test_default_none(self):
        p = PromptTokensDetails()
        assert p.cached_tokens is None

    def test_with_value(self):
        p = PromptTokensDetails(cached_tokens=100)
        assert p.cached_tokens == 100

    def test_extra_kwargs_accepted(self):
        p = PromptTokensDetails(cached_tokens=50, other_field="ignored")
        assert p.cached_tokens == 50
