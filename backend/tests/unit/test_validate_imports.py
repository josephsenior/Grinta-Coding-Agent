"""Tests for backend.validate_imports module.

Targets 0% coverage (43 statements).
"""

from __future__ import annotations

from unittest.mock import patch


from backend.validate_imports import try_import


class TestTryImport:
    def test_successful_import(self):
        assert try_import("os") is True

    def test_import_error(self):
        result = try_import("nonexistent_module_xyz_123")
        assert result is False

    def test_import_error_with_description(self):
        result = try_import("nonexistent_module_xyz_456", "A critical module")
        assert result is False

    def test_generic_exception_returns_false(self):
        with patch("builtins.__import__", side_effect=RuntimeError("kaboom")):
            result = try_import("os", "os module")
        assert result is False

    def test_successful_import_of_real_module(self):
        assert try_import("json", "JSON library") is True

    def test_import_sys(self):
        assert try_import("sys") is True
