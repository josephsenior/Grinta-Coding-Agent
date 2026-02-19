"""Tests for backend.core.type_safety.sentinels — Sentinel objects and helpers."""

from __future__ import annotations


from backend.core.type_safety.sentinels import (
    MISSING,
    NOT_SET,
    coalesce,
    default_if_missing,
    is_missing,
    is_not_set,
    is_set,
)


# ---------------------------------------------------------------------------
# Sentinel class
# ---------------------------------------------------------------------------


class TestSentinel:
    """Tests for the Sentinel base class."""

    def test_repr(self):
        assert repr(MISSING) == "<Sentinel>"

    def test_falsy(self):
        assert not MISSING
        assert not NOT_SET

    def test_bool_false(self):
        assert bool(MISSING) is False
        assert bool(NOT_SET) is False

    def test_equal_to_self_only(self):
        assert MISSING == MISSING
        assert NOT_SET == NOT_SET
        assert MISSING != NOT_SET
        assert MISSING is not None
        assert MISSING != 0
        assert MISSING != ""

    def test_hashable(self):
        """Sentinels can be used in sets and as dict keys."""
        s = {MISSING, NOT_SET}
        assert len(s) == 2
        d = {MISSING: "missing", NOT_SET: "not set"}
        assert d[MISSING] == "missing"

    def test_identity(self):
        assert MISSING is MISSING
        assert NOT_SET is NOT_SET
        assert MISSING is not NOT_SET


# ---------------------------------------------------------------------------
# is_missing / is_not_set / is_set
# ---------------------------------------------------------------------------


class TestSentinelChecks:
    """Tests for sentinel check functions."""

    def test_is_missing(self):
        assert is_missing(MISSING) is True
        assert is_missing(NOT_SET) is False
        assert is_missing(None) is False
        assert is_missing("value") is False
        assert is_missing(0) is False

    def test_is_not_set(self):
        assert is_not_set(NOT_SET) is True
        assert is_not_set(MISSING) is False
        assert is_not_set(None) is False
        assert is_not_set("") is False

    def test_is_set(self):
        assert is_set("value") is True
        assert is_set(None) is True  # None IS a set value
        assert is_set(0) is True
        assert is_set("") is True
        assert is_set(MISSING) is False
        assert is_set(NOT_SET) is False


# ---------------------------------------------------------------------------
# default_if_missing
# ---------------------------------------------------------------------------


class TestDefaultIfMissing:
    """Tests for default_if_missing."""

    def test_returns_default_for_missing(self):
        assert default_if_missing(MISSING, "default") == "default"

    def test_returns_value_when_set(self):
        assert default_if_missing("hello", "default") == "hello"

    def test_returns_none_when_none(self):
        assert default_if_missing(None, "default") is None

    def test_returns_zero_when_zero(self):
        assert default_if_missing(0, 42) == 0


# ---------------------------------------------------------------------------
# coalesce
# ---------------------------------------------------------------------------


class TestCoalesce:
    """Tests for coalesce."""

    def test_first_real_value(self):
        assert coalesce(MISSING, NOT_SET, None, "value") == "value"

    def test_all_sentinels_returns_none(self):
        assert coalesce(MISSING, NOT_SET) is None

    def test_all_none_returns_none(self):
        assert coalesce(MISSING, None) is None

    def test_first_non_sentinel_non_none(self):
        assert coalesce(MISSING, 0) == 0
        assert coalesce(NOT_SET, "", "late") == ""

    def test_single_value(self):
        assert coalesce("only") == "only"

    def test_empty_returns_none(self):
        assert coalesce() is None
