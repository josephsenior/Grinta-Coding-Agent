"""Unit tests for backend.core.type_safety.type_safety — safe wrapper types."""

from __future__ import annotations

import pytest

from backend.core.type_safety.type_safety import (
    NonEmptyString,
    PositiveInt,
    SafeDict,
    SafeList,
    validate_non_empty_string,
    validate_positive_int,
)


# ---------------------------------------------------------------------------
# NonEmptyString
# ---------------------------------------------------------------------------


class TestNonEmptyString:
    def test_valid(self):
        s = NonEmptyString.validate("hello")
        assert s == "hello"
        assert isinstance(s, str)

    def test_empty(self):
        with pytest.raises(ValueError, match="non-empty"):
            NonEmptyString.validate("")

    def test_whitespace(self):
        with pytest.raises(ValueError, match="whitespace"):
            NonEmptyString.validate("   ")

    def test_none(self):
        with pytest.raises(ValueError, match="non-empty"):
            NonEmptyString.validate(None)  # type: ignore[arg-type]

    def test_preserves_value(self):
        s = NonEmptyString.validate("  padded  ")
        assert s == "  padded  "


# ---------------------------------------------------------------------------
# PositiveInt
# ---------------------------------------------------------------------------


class TestPositiveInt:
    def test_valid(self):
        n = PositiveInt.validate(5)
        assert n == 5
        assert isinstance(n, int)

    def test_zero(self):
        with pytest.raises(ValueError, match="positive"):
            PositiveInt.validate(0)

    def test_negative(self):
        with pytest.raises(ValueError, match="positive"):
            PositiveInt.validate(-3)

    def test_non_int(self):
        with pytest.raises(ValueError, match="integer"):
            PositiveInt.validate(3.14)  # type: ignore[arg-type]

    def test_large(self):
        n = PositiveInt.validate(999_999)
        assert n == 999_999


# ---------------------------------------------------------------------------
# SafeList
# ---------------------------------------------------------------------------


class TestSafeList:
    def test_safe_get_valid(self):
        sl = SafeList([10, 20, 30])
        assert sl.safe_get(1) == 20

    def test_safe_get_out_of_bounds(self):
        sl = SafeList([1])
        assert sl.safe_get(5) is None

    def test_safe_get_default(self):
        sl = SafeList([1])
        assert sl.safe_get(5, default=42) == 42

    def test_safe_get_negative(self):
        sl = SafeList([10, 20])
        assert sl.safe_get(-1) == 20  # uses normal python indexing

    def test_safe_slice_normal(self):
        sl = SafeList([1, 2, 3, 4, 5])
        result = sl.safe_slice(1, 3)
        assert result == [2, 3]
        assert isinstance(result, SafeList)

    def test_safe_slice_clamped(self):
        sl = SafeList([1, 2, 3])
        result = sl.safe_slice(0, 100)
        assert result == [1, 2, 3]

    def test_safe_slice_negative_start(self):
        sl = SafeList([1, 2, 3])
        result = sl.safe_slice(-5, 2)
        assert result == [1, 2]

    def test_safe_slice_no_end(self):
        sl = SafeList([1, 2, 3])
        result = sl.safe_slice(1)
        assert result == [2, 3]

    def test_empty_list(self):
        sl = SafeList()
        assert sl.safe_get(0) is None
        assert sl.safe_slice(0, 5) == []


# ---------------------------------------------------------------------------
# SafeDict
# ---------------------------------------------------------------------------


class TestSafeDict:
    def test_safe_get_present(self):
        sd = SafeDict({"a": 1, "b": 2})
        assert sd.safe_get("a") == 1

    def test_safe_get_missing(self):
        sd = SafeDict({"a": 1})
        assert sd.safe_get("z") is None

    def test_safe_get_default(self):
        sd = SafeDict({"a": 1})
        assert sd.safe_get("z", default=99) == 99

    def test_require_present(self):
        sd = SafeDict({"key": "value"})
        assert sd.require("key") == "value"

    def test_require_missing(self):
        sd = SafeDict({"a": 1})
        with pytest.raises(KeyError, match="Required key missing: z"):
            sd.require("z")

    def test_dict_operations(self):
        sd = SafeDict({"x": 10})
        sd["y"] = 20
        assert len(sd) == 2
        assert "y" in sd


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


class TestValidateNonEmptyString:
    def test_valid(self):
        assert validate_non_empty_string("hello", "param") == "hello"

    def test_empty(self):
        with pytest.raises(ValueError, match="param"):
            validate_non_empty_string("", "param")

    def test_whitespace(self):
        with pytest.raises(ValueError, match="param"):
            validate_non_empty_string("   ", "param")


class TestValidatePositiveInt:
    def test_valid(self):
        assert validate_positive_int(3, "count") == 3

    def test_zero(self):
        with pytest.raises(ValueError, match="count"):
            validate_positive_int(0, "count")

    def test_negative(self):
        with pytest.raises(ValueError, match="count"):
            validate_positive_int(-1, "count")

    def test_non_int(self):
        with pytest.raises(ValueError, match="count"):
            validate_positive_int(1.5, "count")  # type: ignore[arg-type]
