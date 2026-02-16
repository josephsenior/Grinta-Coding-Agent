"""Tests for backend.utils.import_utils — dynamic import helpers."""

from __future__ import annotations

import pytest

from backend.utils.import_utils import (
    _impl_matches_base,
    _raise_invalid_impl,
    get_impl,
    import_from,
)


# ---------------------------------------------------------------------------
# import_from
# ---------------------------------------------------------------------------

class TestImportFrom:
    def test_import_existing_class(self):
        cls = import_from("collections.OrderedDict")
        from collections import OrderedDict
        assert cls is OrderedDict

    def test_import_existing_function(self):
        fn = import_from("os.path.join")
        import os.path
        assert fn is os.path.join

    def test_import_nonexistent_module(self):
        with pytest.raises(ModuleNotFoundError):
            import_from("nonexistent_module_xyz.Foo")

    def test_import_nonexistent_attr(self):
        with pytest.raises(AttributeError):
            import_from("os.path.nonexistent_function_xyz")


# ---------------------------------------------------------------------------
# _impl_matches_base
# ---------------------------------------------------------------------------

class TestImplMatchesBase:
    def test_same_class(self):
        assert _impl_matches_base(Exception, Exception) is True

    def test_subclass(self):
        assert _impl_matches_base(Exception, ValueError) is True

    def test_unrelated(self):
        assert _impl_matches_base(int, str) is False


# ---------------------------------------------------------------------------
# get_impl
# ---------------------------------------------------------------------------

class TestGetImpl:
    def test_none_returns_base(self):
        # Clear LRU cache to avoid cross-test interference
        get_impl.cache_clear()
        result = get_impl(Exception, None)
        assert result is Exception

    def test_valid_impl(self):
        get_impl.cache_clear()
        # OrderedDict is a subclass of dict
        result = get_impl(dict, "collections.OrderedDict")
        from collections import OrderedDict
        assert result is OrderedDict

    def test_invalid_impl_raises(self):
        get_impl.cache_clear()
        with pytest.raises(AssertionError, match="not a subclass"):
            get_impl(int, "collections.OrderedDict")


# ---------------------------------------------------------------------------
# _raise_invalid_impl
# ---------------------------------------------------------------------------

class TestRaiseInvalidImpl:
    def test_raises_assertion(self):
        with pytest.raises(AssertionError, match="not a subclass"):
            _raise_invalid_impl(int, str)
