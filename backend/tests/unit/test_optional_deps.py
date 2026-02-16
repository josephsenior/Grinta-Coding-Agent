"""Tests for backend.core.optional_deps — require_optional helper."""

import pytest

from backend.core.optional_deps import OptionalDependencyError, require_optional


class TestRequireOptional:
    def test_existing_module(self):
        """Should successfully import an existing module."""
        result = require_optional("json", extra="core")
        import json
        assert result is json

    def test_missing_module_raises(self):
        """Should raise OptionalDependencyError for missing module."""
        with pytest.raises(OptionalDependencyError, match="no_such_module_xyz"):
            require_optional("no_such_module_xyz", extra="test")

    def test_error_message_includes_extra(self):
        """Error message should include pip install instruction with extra name."""
        with pytest.raises(OptionalDependencyError, match="forge-ai\\[my_extra\\]"):
            require_optional("nonexistent_pkg_abc", extra="my_extra")

    def test_error_is_import_error(self):
        """OptionalDependencyError should be subclass of ImportError."""
        assert issubclass(OptionalDependencyError, ImportError)
        with pytest.raises(ImportError):
            require_optional("nonexistent_pkg_abc", extra="x")

    def test_nested_module(self):
        """Should import nested modules like os.path."""
        result = require_optional("os.path", extra="core")
        import os.path
        assert result is os.path
