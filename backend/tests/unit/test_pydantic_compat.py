"""Tests for backend.core.pydantic_compat — Pydantic v1/v2 compatibility."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from backend.core.pydantic_compat import (
    get_model_field_names,
    model_dump_json,
    model_dump_with_options,
    model_to_dict,
)


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------

class SampleModel(BaseModel):
    name: str = "default"
    value: int = 42


class NestedModel(BaseModel):
    inner: SampleModel = SampleModel()
    flag: bool = True


# ===================================================================
# model_to_dict
# ===================================================================

class TestModelToDict:

    def test_pydantic_model(self):
        m = SampleModel(name="test", value=99)
        d = model_to_dict(m)
        assert d == {"name": "test", "value": 99}

    def test_plain_dict_passthrough(self):
        d = {"a": 1, "b": 2}
        result = model_to_dict(d)
        assert result == d

    def test_primitive_passthrough(self):
        assert model_to_dict(42) == 42

    def test_nested_model(self):
        m = NestedModel(inner=SampleModel(name="nested"))
        d = model_to_dict(m)
        assert d["inner"]["name"] == "nested"

    def test_string_passthrough(self):
        assert model_to_dict("hello") == "hello"


# ===================================================================
# get_model_field_names
# ===================================================================

class TestGetModelFieldNames:

    def test_pydantic_v2_model(self):
        fields = get_model_field_names(SampleModel)
        assert "name" in fields
        assert "value" in fields

    def test_plain_class_with_annotations(self):
        class Plain:
            x: int
            y: str

        fields = get_model_field_names(Plain)
        assert "x" in fields
        assert "y" in fields

    def test_empty_class(self):
        class Empty:
            pass

        fields = get_model_field_names(Empty)
        assert fields == set()


# ===================================================================
# model_dump_with_options
# ===================================================================

class TestModelDumpWithOptions:

    def test_default_dump(self):
        m = SampleModel(name="test", value=1)
        d = model_dump_with_options(m)
        assert isinstance(d, dict)
        assert d["name"] == "test"
        assert d["value"] == 1

    def test_exclude_fields(self):
        m = SampleModel(name="test", value=1)
        d = model_dump_with_options(m, exclude={"value"})
        assert "value" not in d
        assert d["name"] == "test"

    def test_plain_object_fallback(self):
        """For objects without model_dump, falls back gracefully."""
        class Fake:
            pass
        obj = Fake()
        # Should not raise
        result = model_dump_with_options(obj)
        assert result is not None


# ===================================================================
# model_dump_json
# ===================================================================

class TestModelDumpJson:

    def test_returns_json_string(self):
        m = SampleModel(name="json_test", value=7)
        s = model_dump_json(m)
        assert isinstance(s, str)
        parsed = json.loads(s)
        assert parsed["name"] == "json_test"

    def test_nested_model_json(self):
        m = NestedModel()
        s = model_dump_json(m)
        parsed = json.loads(s)
        assert "inner" in parsed
        assert parsed["flag"] is True

    def test_plain_object_fallback(self):
        """For non-Pydantic objects, still produces valid JSON."""
        class Plain:
            x = 42
        result = model_dump_json(Plain())
        assert isinstance(result, str)
        # Should not raise
        json.loads(result)
