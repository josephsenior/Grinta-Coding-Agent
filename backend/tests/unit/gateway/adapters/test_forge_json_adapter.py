"""Tests for backend.gateway.adapters.json — ForgeJSONEncoder, dumps, loads."""

from __future__ import annotations

import json
from datetime import datetime, UTC

import pytest

from backend.gateway.adapters.json import ForgeJSONEncoder, dumps, loads
from backend.core.errors import LLMResponseError


# ── ForgeJSONEncoder ─────────────────────────────────────────────────


class TestForgeJSONEncoder:
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)
        result = json.dumps({"time": dt}, cls=ForgeJSONEncoder)
        data = json.loads(result)
        assert "2024-01-15" in data["time"]

    def test_plain_dict(self):
        result = json.dumps({"key": "value"}, cls=ForgeJSONEncoder)
        assert json.loads(result) == {"key": "value"}

    def test_list(self):
        result = json.dumps([1, 2, 3], cls=ForgeJSONEncoder)
        assert json.loads(result) == [1, 2, 3]

    def test_nested(self):
        dt = datetime(2024, 6, 1, tzinfo=UTC)
        result = json.dumps({"nested": {"time": dt}}, cls=ForgeJSONEncoder)
        data = json.loads(result)
        assert "2024-06-01" in data["nested"]["time"]


# ── dumps ────────────────────────────────────────────────────────────


class TestDumps:
    def test_simple_dict(self):
        result = dumps({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_with_datetime(self):
        dt = datetime(2024, 3, 15, tzinfo=UTC)
        result = dumps({"t": dt})
        assert "2024-03-15" in result

    def test_string(self):
        result = dumps("hello")
        assert json.loads(result) == "hello"

    def test_number(self):
        result = dumps(42)
        assert json.loads(result) == 42

    def test_with_indent(self):
        result = dumps({"a": 1}, indent=2)
        assert "\n" in result

    def test_none(self):
        result = dumps(None)
        assert json.loads(result) is None


# ── loads ────────────────────────────────────────────────────────────


class TestLoads:
    def test_valid_json(self):
        assert loads('{"key": "value"}') == {"key": "value"}

    def test_valid_list(self):
        assert loads("[1, 2, 3]") == [1, 2, 3]

    def test_nested_json(self):
        result = loads('{"a": {"b": 1}}')
        assert result["a"]["b"] == 1

    def test_invalid_json_no_object(self):
        with pytest.raises(LLMResponseError, match="No valid JSON"):
            loads("this is not json at all")

    def test_json_embedded_in_text(self):
        result = loads('Here is the response: {"key": "value"} end')
        assert result == {"key": "value"}

    def test_roundtrip(self):
        original = {"numbers": [1, 2, 3], "text": "hello"}
        assert loads(dumps(original)) == original
