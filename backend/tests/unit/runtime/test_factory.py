"""Tests for backend.runtime.factory — runtime class loading and resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.runtime.factory import _DEFAULT_RUNTIME_IMPORTS, _lazy_import, get_runtime_cls


# ── _lazy_import function ──────────────────────────────────────────────


class TestLazyImport:
    """Test lazy module import and attribute retrieval."""

    def test_imports_module_and_gets_attribute(self):
        """Test importing a real module and getting an attribute."""
        result = _lazy_import("backend.runtime.base", "Runtime")
        assert result.__name__ == "Runtime"

    def test_imports_function(self):
        """Test importing a function from a module."""
        result = _lazy_import("backend.runtime.factory", "get_runtime_cls")
        assert callable(result)
        assert result.__name__ == "get_runtime_cls"

    def test_raises_on_invalid_module(self):
        """Test raises when module doesn't exist."""
        with pytest.raises(ModuleNotFoundError):
            _lazy_import("backend.nonexistent.module", "SomeClass")

    def test_raises_on_missing_attribute(self):
        """Test raises when attribute doesn't exist in module."""
        with pytest.raises(AttributeError):
            _lazy_import("backend.runtime.base", "NonExistentClass")

    @patch("backend.runtime.factory.importlib.import_module")
    def test_calls_importlib(self, mock_import):
        """Test uses importlib.import_module."""
        mock_module = MagicMock()
        mock_module.TestAttr = "test_value"
        mock_import.return_value = mock_module

        result = _lazy_import("some.module", "TestAttr")

        mock_import.assert_called_once_with("some.module")
        assert result == "test_value"


# ── get_runtime_cls function ───────────────────────────────────────────


class TestGetRuntimeCls:
    """Test runtime class resolution."""

    def test_resolves_local_runtime(self):
        """Test resolving 'local' built-in runtime."""
        cls = get_runtime_cls("local")
        assert cls.__name__ == "LocalRuntimeInProcess"
        # Verify it's a runtime class
        from backend.runtime.base import Runtime
        assert issubclass(cls, Runtime)

    def test_raises_on_unknown_runtime(self):
        """Test raises ValueError on unknown runtime name."""
        with pytest.raises(ValueError, match="Runtime unknown_runtime not supported"):
            get_runtime_cls("unknown_runtime")

    def test_error_includes_known_keys(self):
        """Test error message includes known runtime keys."""
        with pytest.raises(ValueError, match="known are"):
            get_runtime_cls("nonexistent")

    @patch("backend.runtime.factory._lazy_import")
    def test_uses_lazy_import_for_builtin(self, mock_lazy):
        """Test uses lazy import for built-in runtimes."""
        mock_lazy.return_value = MagicMock()

        get_runtime_cls("local")

        # Verify it called lazy import with correct module/attr from defaults
        module_path, attr = _DEFAULT_RUNTIME_IMPORTS["local"]
        mock_lazy.assert_called_once_with(module_path, attr)

    @patch("backend.runtime.factory.get_impl")
    def test_falls_back_to_get_impl(self, mock_get_impl):
        """Test falls back to get_impl for custom runtime classes."""
        from backend.runtime.base import Runtime

        mock_runtime = MagicMock(spec=Runtime)
        mock_get_impl.return_value = mock_runtime

        result = get_runtime_cls("custom.runtime.MyRuntime")

        mock_get_impl.assert_called_once_with(Runtime, "custom.runtime.MyRuntime")
        assert result == mock_runtime

    @patch("backend.runtime.factory.get_impl")
    def test_get_impl_failure_reraises_with_context(self, mock_get_impl):
        """Test get_impl failure is re-raised as ValueError with context."""
        mock_get_impl.side_effect = ImportError("Module not found")

        with pytest.raises(ValueError, match="Runtime custom not supported"):
            get_runtime_cls("custom")


# ── _DEFAULT_RUNTIME_IMPORTS constant ──────────────────────────────────


class TestDefaultRuntimeImports:
    """Test default runtime imports configuration."""

    def test_contains_local_key(self):
        """Test contains 'local' key."""
        assert "local" in _DEFAULT_RUNTIME_IMPORTS

    def test_local_maps_to_correct_module(self):
        """Test 'local' maps to LocalRuntimeInProcess."""
        module_path, attr = _DEFAULT_RUNTIME_IMPORTS["local"]
        assert module_path == "backend.runtime.drivers.local.local_runtime_inprocess"
        assert attr == "LocalRuntimeInProcess"

    def test_is_dict_of_tuples(self):
        """Test structure is dict[str, tuple[str, str]]."""
        for key, value in _DEFAULT_RUNTIME_IMPORTS.items():
            assert isinstance(key, str)
            assert isinstance(value, tuple)
            assert len(value) == 2
            assert isinstance(value[0], str)  # module path
            assert isinstance(value[1], str)  # attribute name
