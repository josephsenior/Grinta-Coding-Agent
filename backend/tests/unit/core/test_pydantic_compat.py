"""Tests for backend.core.pydantic_compat — Pydantic v1/v2 compatibility."""

from __future__ import annotations

import json
from unittest.mock import patch

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

    def test_model_dump_error_falls_back_to_dict(self):
        class Fake:
            def model_dump(self):
                raise RuntimeError("boom")

            def dict(self):
                return {"ok": True}

        assert model_to_dict(Fake()) == {"ok": True}

    def test_dict_error_falls_back_to_json_roundtrip(self):
        class Fake:
            def dict(self):
                raise RuntimeError("boom")

            def __str__(self) -> str:
                return "fake"

        assert model_to_dict(Fake()) == "fake"

    def test_json_roundtrip_error_returns_object(self):
        class Fake:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        obj = Fake()
        assert model_to_dict(obj) is obj


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

    def test_model_fields_not_dict_falls_back(self):
        class Fake:
            model_fields = ["x"]
            __annotations__ = {"x": int}

        fields = get_model_field_names(Fake)
        assert fields == {"x"}

    def test_fields_property_raises_falls_back(self):
        class Fake:
            __annotations__ = {"x": int}

            @property
            def __fields__(self):  # type: ignore[override]
                raise RuntimeError("boom")

        fields = get_model_field_names(Fake)
        assert fields == {"x"}

    def test_model_fields_accessor_raises(self):
        class Fake:
            __annotations__ = {"x": int}

            def __getattribute__(self, name):
                if name == "model_fields":
                    raise RuntimeError("boom")
                if name == "__fields__":
                    raise AttributeError("boom")
                return super().__getattribute__(name)

        fields = get_model_field_names(Fake())
        assert fields == {"x"}


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

    def test_model_dump_exception_falls_back_to_dict(self):
        class Fake:
            def model_dump(self, **_kwargs):
                raise RuntimeError("boom")

            def dict(self, **_kwargs):
                return {"ok": 1}

        assert model_dump_with_options(Fake()) == {"ok": 1}

    def test_mode_json_uses_json_method(self):
        class Fake:
            def json(self, **_kwargs):
                return '{"ok": 2}'

            def dict(self, **_kwargs):
                raise RuntimeError("should not call dict")

        assert model_dump_with_options(Fake(), mode="json") == {"ok": 2}

    def test_invalid_json_falls_back_to_dict(self):
        class Fake:
            def json(self, **_kwargs):
                return "not json"

            def dict(self, **_kwargs):
                return {"ok": 3}

        assert model_dump_with_options(Fake(), mode="json") == {"ok": 3}

    def test_dict_exception_falls_back_to_model_to_dict(self):
        class Fake:
            def dict(self, **_kwargs):
                raise RuntimeError("boom")

            def __str__(self) -> str:
                return "fallback"

        assert model_dump_with_options(Fake()) == "fallback"


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

    def test_model_dump_json_falls_back_to_json(self):
        class Fake:
            def model_dump_json(self, **_kwargs):
                raise RuntimeError("boom")

            def json(self, **_kwargs):
                return '{"ok": 4}'

        result = model_dump_json(Fake())
        assert json.loads(result)["ok"] == 4

    def test_model_dump_json_falls_back_to_dump_options(self):
        class Fake:
            def model_dump_json(self, **_kwargs):
                raise RuntimeError("boom")

            def json(self, **_kwargs):
                raise RuntimeError("boom")

            def dict(self, **_kwargs):
                return {"ok": 5}

        result = model_dump_json(Fake())
        assert json.loads(result)["ok"] == 5

    def test_model_dump_json_final_fallback(self):
        class Fake:
            def model_dump_json(self, **_kwargs):
                raise RuntimeError("boom")

            def json(self, **_kwargs):
                raise RuntimeError("boom")

            def __str__(self) -> str:
                return "fallback"

        with patch(
            "backend.core.pydantic_compat.model_dump_with_options",
            side_effect=RuntimeError("boom"),
        ):
            result = model_dump_json(Fake())

        assert json.loads(result) == "fallback"
