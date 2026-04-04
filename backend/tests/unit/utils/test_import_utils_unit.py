"""Tests for backend.utils.import_utils — Dynamic import / get_impl utilities."""

from __future__ import annotations

import pytest

from backend.utils.import_utils import (
    _impl_matches_base,
    _raise_invalid_impl,
    get_impl,
    import_from,
)

# ── import_from ──────────────────────────────────────────────────────


class TestImportFrom:
    def test_import_class(self):
        cls = import_from('backend.utils.import_utils.import_from')
        assert cls is import_from

    def test_import_module_level_function(self):
        fn = import_from('os.path.join')
        import os.path

        assert fn is os.path.join

    def test_import_nonexistent_module(self):
        with pytest.raises(ModuleNotFoundError):
            import_from('nonexistent_package_xyz.Foo')

    def test_import_nonexistent_attr(self):
        with pytest.raises(AttributeError):
            import_from('os.path.nonexistent_attr_xyz')


# ── _impl_matches_base ──────────────────────────────────────────────


class TestImplMatchesBase:
    def test_same_class(self):
        assert _impl_matches_base(ValueError, ValueError)

    def test_subclass(self):
        class MyError(ValueError):
            pass

        assert _impl_matches_base(ValueError, MyError)

    def test_unrelated(self):
        assert not _impl_matches_base(ValueError, TypeError)


# ── _raise_invalid_impl ─────────────────────────────────────────────


class TestRaiseInvalidImpl:
    def test_raises_assertion(self):
        with pytest.raises(AssertionError, match='not a subclass'):
            _raise_invalid_impl(ValueError, TypeError)


# ── get_impl ─────────────────────────────────────────────────────────


class TestGetImpl:
    def setup_method(self):
        get_impl.cache_clear()

    def teardown_method(self):
        get_impl.cache_clear()

    def test_none_returns_base(self):
        assert get_impl(ValueError, None) is ValueError

    def test_valid_impl(self):
        # KeyError is a subclass of LookupError
        result = get_impl(LookupError, 'builtins.KeyError')
        assert result is KeyError

    def test_same_class_by_name(self):
        result = get_impl(ValueError, 'builtins.ValueError')
        assert result is ValueError

    def test_invalid_impl_raises(self):
        with pytest.raises(AssertionError, match='not a subclass'):
            get_impl(ValueError, 'builtins.TypeError')

    def test_caching(self):
        r1 = get_impl(LookupError, 'builtins.KeyError')
        r2 = get_impl(LookupError, 'builtins.KeyError')
        assert r1 is r2
