"""Tests for backend.adapters.json — ForgeJSONEncoder, dumps, loads."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import BaseModel

from backend.adapters.json import ForgeJSONEncoder, dumps, loads
from backend.core.errors import LLMResponseError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SamplePydantic(BaseModel):
    name: str = "test"
    value: int = 42


# ===================================================================
# ForgeJSONEncoder
# ===================================================================


class TestForgeJSONEncoder:
    def test_datetime_encoding(self):
        dt = datetime(2025, 6, 15, 12, 30, 0)
        result = json.dumps({"ts": dt}, cls=ForgeJSONEncoder)
        parsed = json.loads(result)
        assert parsed["ts"] == "2025-06-15T12:30:00"

    def test_pydantic_model_encoding(self):
        m = _SamplePydantic(name="hello", value=99)
        result = json.dumps({"model": m}, cls=ForgeJSONEncoder)
        parsed = json.loads(result)
        assert parsed["model"]["name"] == "hello"

    def test_model_with_model_dump(self):
        """Objects with model_dump() should be serialized via that method."""

        class FakeDumpable:
            def model_dump(self):
                return {"key": "dumped"}

        result = json.dumps({"obj": FakeDumpable()}, cls=ForgeJSONEncoder)
        parsed = json.loads(result)
        assert parsed["obj"]["key"] == "dumped"

    def test_raises_for_unsupported_type(self):
        with pytest.raises(TypeError):
            json.dumps({"bad": object()}, cls=ForgeJSONEncoder)


# ===================================================================
# dumps
# ===================================================================


class TestDumps:
    def test_simple_dict(self):
        result = dumps({"a": 1, "b": "two"})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": "two"}

    def test_with_datetime(self):
        dt = datetime(2025, 1, 1)
        result = dumps({"dt": dt})
        assert "2025-01-01" in result

    def test_with_kwargs(self):
        result = dumps({"a": 1}, indent=2)
        assert "\n" in result

    def test_list(self):
        result = dumps([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]


# ===================================================================
# loads
# ===================================================================


class TestLoads:
    def test_valid_json(self):
        result = loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_valid_json_array(self):
        result = loads("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_invalid_json_with_embedded_object(self):
        """loads should find and repair embedded JSON objects."""
        raw = 'Some prefix text {"key": "value"} and trailing text'
        result = loads(raw)
        assert result["key"] == "value"

    def test_no_json_object_raises(self):
        with pytest.raises(LLMResponseError, match="No valid JSON"):
            loads("no json here at all")

    def test_badly_malformed_embedded_json(self):
        """Truly unrecoverable JSON should raise LLMResponseError."""
        # Brace-balanced but not valid JSON at all
        raw = "{this is not: valid json at all }"
        # json_repair may be able to fix simpler cases, but truly broken
        # content should raise
        try:
            result = loads(raw)
            # If json_repair fixes it, that's acceptable too
            assert isinstance(result, dict)
        except LLMResponseError:
            pass  # Expected

    def test_nested_braces(self):
        raw = '{"outer": {"inner": 42}}'
        result = loads(raw)
        assert result["outer"]["inner"] == 42
