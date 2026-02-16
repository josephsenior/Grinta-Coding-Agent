"""Unit tests for backend.core.config.env_loader — env var type casting."""

from __future__ import annotations

from typing import Optional

import pytest
from pydantic import SecretStr

from backend.core.config.env_loader import (
    _get_optional_type,
    _is_dict_or_list_type,
    cast_value_to_type,
    restore_environment,
)


# ---------------------------------------------------------------------------
# cast_value_to_type
# ---------------------------------------------------------------------------


class TestCastValueToType:
    def test_bool_true(self):
        assert cast_value_to_type("true", bool) is True
        assert cast_value_to_type("1", bool) is True

    def test_bool_false(self):
        assert cast_value_to_type("false", bool) is False
        assert cast_value_to_type("0", bool) is False
        assert cast_value_to_type("no", bool) is False

    def test_int(self):
        assert cast_value_to_type("42", int) == 42

    def test_float(self):
        assert cast_value_to_type("3.14", float) == pytest.approx(3.14)

    def test_str(self):
        assert cast_value_to_type("hello", str) == "hello"

    def test_secret_str(self):
        result = cast_value_to_type("s3cret", SecretStr)
        assert isinstance(result, SecretStr)
        assert result.get_secret_value() == "s3cret"

    def test_dict_literal(self):
        result = cast_value_to_type('{"a": 1}', dict)
        assert result == {"a": 1}

    def test_list_literal(self):
        result = cast_value_to_type('[1, 2, 3]', list)
        assert result == [1, 2, 3]

    def test_none_type_passthrough(self):
        assert cast_value_to_type("hello", None) == "hello"

    def test_optional_int(self):
        result = cast_value_to_type("42", int | None)
        assert result == 42


# ---------------------------------------------------------------------------
# _get_optional_type
# ---------------------------------------------------------------------------


class TestGetOptionalType:
    def test_none_input(self):
        assert _get_optional_type(None) is None

    def test_plain_type(self):
        assert _get_optional_type(int) is int

    def test_union_with_none(self):
        result = _get_optional_type(int | None)
        assert result is int


# ---------------------------------------------------------------------------
# _is_dict_or_list_type
# ---------------------------------------------------------------------------


class TestIsDictOrListType:
    def test_dict(self):
        assert _is_dict_or_list_type(dict) is True

    def test_list(self):
        assert _is_dict_or_list_type(list) is True

    def test_typed_dict(self):
        assert _is_dict_or_list_type(dict[str, int]) is True

    def test_typed_list(self):
        assert _is_dict_or_list_type(list[int]) is True

    def test_str(self):
        assert _is_dict_or_list_type(str) is False

    def test_int(self):
        assert _is_dict_or_list_type(int) is False


# ---------------------------------------------------------------------------
# restore_environment
# ---------------------------------------------------------------------------


class TestRestoreEnvironment:
    def test_removes_added_keys(self, monkeypatch):
        import os

        original = dict(os.environ)
        monkeypatch.setenv("FORGE_TEST_NEW_KEY", "val")
        restore_environment(original)
        assert "FORGE_TEST_NEW_KEY" not in os.environ

    def test_restores_changed_keys(self, monkeypatch):
        import os

        original = dict(os.environ)
        original["FORGE_TEST_KEY"] = "original"
        monkeypatch.setenv("FORGE_TEST_KEY", "changed")
        restore_environment(original)
        assert os.environ.get("FORGE_TEST_KEY") == "original"
