"""Tests for backend.utils.import_utils — dynamic import and validation."""

import sys
from unittest.mock import MagicMock

import pytest

from backend.utils.import_utils import (
    import_from,
    get_impl,
    _impl_matches_base,
    _matches_qualified_name_in_mro,
    _reimport_base_class,
    _matches_reimported_base,
    _raise_invalid_impl,
)


class TestImportFrom:
    """Tests for import_from function."""

    def test_import_builtin_class(self):
        """Test importing a builtin class."""
        result = import_from("builtins.dict")
        assert result is dict

    def test_import_stdlib_module(self):
        """Test importing from stdlib."""
        result = import_from("os.path.join")
        from os.path import join

        assert result is join

    def test_import_type(self):
        """Test importing a type."""
        import typing

        result = import_from("typing.List")
        assert result is typing.List

    def test_import_function(self):
        """Test importing a function."""
        result = import_from("os.path.exists")
        from os.path import exists

        assert result is exists

    def test_import_from_nested_module(self):
        """Test importing from deeply nested module."""
        result = import_from("unittest.mock.MagicMock")
        assert result is MagicMock

    def test_import_nonexistent_module(self):
        """Test importing from nonexistent module raises."""
        with pytest.raises(ModuleNotFoundError):
            import_from("nonexistent.module.Class")

    def test_import_nonexistent_attr(self):
        """Test importing nonexistent attribute raises."""
        with pytest.raises(AttributeError):
            import_from("os.path.nonexistent_function")


class TestGetImpl:
    """Tests for get_impl function."""

    def test_none_impl_returns_base(self):
        """Test get_impl with None returns base class unchanged."""
        result = get_impl(dict, None)
        assert result is dict

    def test_same_class_returns_self(self):
        """Test get_impl with same class name returns the class."""
        result = get_impl(list, "builtins.list")
        assert result is list

    def test_subclass_returns_impl(self):
        """Test get_impl with valid subclass."""

        class BaseClass:
            pass

        class SubClass(BaseClass):
            pass

        # Add to module so import_from can find it
        setattr(sys.modules[__name__], "SubClass", SubClass)

        result = get_impl(BaseClass, f"{__name__}.SubClass")
        assert result is SubClass

    def test_invalid_impl_raises(self):
        """Test get_impl with non-subclass raises AssertionError."""

        class BaseClass:
            pass

        class UnrelatedClass:
            pass

        setattr(sys.modules[__name__], "UnrelatedClass", UnrelatedClass)

        with pytest.raises(AssertionError, match="not a subclass"):
            get_impl(BaseClass, f"{__name__}.UnrelatedClass")

    def test_caching(self):
        """Test get_impl caches results."""
        # Call twice with same arguments
        result1 = get_impl(dict, None)
        result2 = get_impl(dict, None)
        assert result1 is result2
        assert result1 is dict

    def test_builtin_subclass(self):
        """Test get_impl with builtin subclass."""

        class MyDict(dict):
            pass

        setattr(sys.modules[__name__], "MyDict", MyDict)
        result = get_impl(dict, f"{__name__}.MyDict")
        assert result is MyDict


class TestImplMatchesBase:
    """Tests for _impl_matches_base function."""

    def test_same_class(self):
        """Test matching with same class."""
        assert _impl_matches_base(dict, dict) is True

    def test_direct_subclass(self):
        """Test matching with direct subclass."""

        class Base:
            pass

        class Sub(Base):
            pass

        assert _impl_matches_base(Base, Sub) is True

    def test_indirect_subclass(self):
        """Test matching with indirect subclass."""

        class Base:
            pass

        class Mid(Base):
            pass

        class Sub(Mid):
            pass

        assert _impl_matches_base(Base, Sub) is True

    def test_unrelated_classes(self):
        """Test non-matching with unrelated classes."""

        class ClassA:
            pass

        class ClassB:
            pass

        # Should check qualified name in MRO
        result = _impl_matches_base(ClassA, ClassB)
        assert result is False


class TestMatchesQualifiedNameInMro:
    """Tests for _matches_qualified_name_in_mro function."""

    def test_match_in_mro(self):
        """Test finding match in MRO by module and name."""

        class Base:
            pass

        Base.__module__ = "test_module"
        Base.__name__ = "BaseClass"

        class Sub(Base):
            pass

        result = _matches_qualified_name_in_mro(Base, Sub)
        assert result is True

    def test_no_match_in_mro(self):
        """Test no match in MRO."""

        class BaseA:
            pass

        BaseA.__module__ = "module_a"
        BaseA.__name__ = "BaseA"

        class BaseB:
            pass

        BaseB.__module__ = "module_b"
        BaseB.__name__ = "BaseB"

        result = _matches_qualified_name_in_mro(BaseA, BaseB)
        assert result is False

    def test_missing_module_attr(self):
        """Test class without __module__ attribute."""
        # Use MagicMock which doesn't have __module__ by default
        base = MagicMock(spec=[])
        setattr(base, "__module__", None)
        setattr(base, "__name__", None)

        impl = MagicMock(spec=[])
        impl.__mro__ = (impl,)

        result = _matches_qualified_name_in_mro(base, impl)
        # Should handle missing __module__ gracefully
        assert isinstance(result, bool)


class TestReimportBaseClass:
    """Tests for _reimport_base_class function."""

    def test_reimport_existing_class(self):
        """Test reimporting an existing class."""
        result = _reimport_base_class("builtins", "dict")
        assert result is dict

    def test_reimport_nonexistent_module(self):
        """Test reimporting from nonexistent module."""
        result = _reimport_base_class("nonexistent", "Class")
        assert result is None

    def test_reimport_nonexistent_class(self):
        """Test reimporting nonexistent class."""
        result = _reimport_base_class("builtins", "NonexistentClass")
        assert result is None

    def test_reimport_non_type(self):
        """Test reimporting something that's not a type."""
        result = _reimport_base_class("sys", "version")
        # sys.version is a string, not a type
        assert result is None


class TestMatchesReimportedBase:
    """Tests for _matches_reimported_base function."""

    def test_matches_reimported(self):
        """Test matching with reimported base."""

        class Base:
            pass

        Base.__module__ = "builtins"
        Base.__name__ = "dict"

        class Sub(dict):
            pass

        result = _matches_reimported_base(Base, Sub)
        assert result is True

    def test_no_match_reimported(self):
        """Test no match with reimported base."""

        class Base:
            pass

        Base.__module__ = "nonexistent"
        Base.__name__ = "Class"

        class Sub:
            pass

        result = _matches_reimported_base(Base, Sub)
        assert result is False

    def test_missing_module_name(self):
        """Test with missing __module__ or __name__."""
        # Use MagicMock which doesn't have __module__ by default
        base = MagicMock(spec=[])
        setattr(base, "__module__", None)
        setattr(base, "__name__", None)

        impl = MagicMock(spec=[])

        result = _matches_reimported_base(base, impl)
        assert result is False


class TestRaiseInvalidImpl:
    """Tests for _raise_invalid_impl function."""

    def test_raises_assertion_error(self):
        """Test raises AssertionError with proper message."""

        class Base:
            pass

        Base.__module__ = "test_module"
        Base.__name__ = "BaseClass"

        class Impl:
            pass

        Impl.__module__ = "impl_module"
        Impl.__name__ = "ImplClass"

        with pytest.raises(
            AssertionError, match="Implementation class is not a subclass"
        ):
            _raise_invalid_impl(Base, Impl)

    def test_error_message_contains_details(self):
        """Test error message contains base and impl details."""

        class Base:
            pass

        Base.__module__ = "base_mod"
        Base.__name__ = "Base"

        class Impl:
            pass

        Impl.__module__ = "impl_mod"
        Impl.__name__ = "Impl"

        with pytest.raises(AssertionError, match="base=base_mod.Base"):
            _raise_invalid_impl(Base, Impl)

        with pytest.raises(AssertionError, match="impl=impl_mod.Impl"):
            _raise_invalid_impl(Base, Impl)
