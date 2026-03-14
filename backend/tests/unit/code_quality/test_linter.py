"""Unit tests for backend.code_quality.impl — LintError, LintResult, DefaultLinter."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.code_quality.impl import DefaultLinter, LintError, LintResult


# ---------------------------------------------------------------------------
# LintError
# ---------------------------------------------------------------------------


class TestLintError:
    def test_visualize_basic(self):
        err = LintError(line=10, column=None, message="bad code")
        v = err.visualize()
        assert "line 10" in v
        assert "bad code" in v

    def test_visualize_with_column(self):
        err = LintError(line=5, column=3, message="oops")
        v = err.visualize()
        assert "column 3" in v

    def test_visualize_with_code(self):
        err = LintError(line=1, column=None, message="x", code="E123")
        v = err.visualize()
        assert "[E123]" in v

    def test_default_severity(self):
        err = LintError(line=1, column=None, message="z")
        assert err.severity == "error"

    def test_custom_severity(self):
        err = LintError(line=1, column=None, message="z", severity="warning")
        assert err.severity == "warning"


# ---------------------------------------------------------------------------
# LintResult
# ---------------------------------------------------------------------------


class TestLintResult:
    def test_separation_in_post_init(self):
        e1 = LintError(line=1, column=None, message="a", severity="error")
        w1 = LintError(line=2, column=None, message="b", severity="warning")
        # Put both in errors list — post_init should separate them
        result = LintResult(errors=[e1, w1], warnings=[])
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert result.errors[0].message == "a"
        assert result.warnings[0].message == "b"

    def test_mixed_lists(self):
        w = LintError(line=1, column=None, message="w", severity="warning")
        e = LintError(line=2, column=None, message="e", severity="error")
        result = LintResult(errors=[w], warnings=[e])
        assert len(result.errors) == 1
        assert result.errors[0].message == "e"
        assert len(result.warnings) == 1
        assert result.warnings[0].message == "w"

    def test_empty(self):
        result = LintResult(errors=[], warnings=[])
        assert result.errors == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# DefaultLinter — cache layer (no subprocess needed)
# ---------------------------------------------------------------------------


class TestDefaultLinterCache:
    """Test the caching logic without invoking actual linter backends."""

    @pytest.fixture()
    def linter(self):
        """A linter with no detected backend (linting returns empty results)."""
        with patch.object(DefaultLinter, "_detect_best_backend", return_value=None):
            return DefaultLinter(backend="auto", enable_cache=True, cache_ttl=5)

    def test_no_backend_returns_empty(self, linter):
        result = linter.lint(content="x = 1")
        assert result.errors == []
        assert result.warnings == []

    def test_cache_stats_initial(self, linter):
        stats = linter.get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0

    def test_clear_cache(self, linter):
        linter._cache["dummy"] = (LintResult([], []), time.time())
        linter._cache_hits = 5
        linter.clear_cache()
        assert not linter._cache
        assert linter._cache_hits == 0
        assert linter._cache_misses == 0

    def test_cache_eviction(self):
        with patch.object(DefaultLinter, "_detect_best_backend", return_value=None):
            linter = DefaultLinter(backend="auto", enable_cache=True, max_cache_size=2)
        # Manually populate 3 entries to trigger eviction
        for i in range(3):
            key = f"lint:k{i}"
            linter._set_cache(key, LintResult([], []))
        assert len(linter._cache) == 2

    def test_cache_expiry(self):
        with patch.object(DefaultLinter, "_detect_best_backend", return_value=None):
            linter = DefaultLinter(backend="auto", enable_cache=True, cache_ttl=0)
        linter._set_cache("key", LintResult([], []))
        # TTL is 0, so immediate retrieval should return None (expired)
        # Need a tiny passage of time
        import time as _time

        _time.sleep(0.01)
        assert linter._get_from_cache("key") is None

    def test_cache_hit(self):
        with patch.object(DefaultLinter, "_detect_best_backend", return_value=None):
            linter = DefaultLinter(backend="auto", enable_cache=True, cache_ttl=300)
        expected = LintResult(
            errors=[LintError(line=1, column=None, message="x")], warnings=[]
        )
        linter._set_cache("key", expected)
        got = linter._get_from_cache("key")
        assert got is expected

    def test_hash_config(self):
        with patch.object(DefaultLinter, "_detect_best_backend", return_value=None):
            linter = DefaultLinter(backend="auto")
        h = linter._hash_config()
        assert isinstance(h, str)
        assert len(h) == 8

    def test_lint_file_diff_delegates(self, linter):
        result = linter.lint_file_diff("a.py", "b.py")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# DefaultLinter — backend detection (mocked subprocess)
# ---------------------------------------------------------------------------


class TestDefaultLinterBackendDetection:
    def test_auto_selects_ruff_if_available(self):
        with patch.object(
            DefaultLinter, "_check_backend_available", side_effect=lambda b: b == "ruff"
        ):
            linter = DefaultLinter(backend="auto")
        assert linter._detected_backend == "ruff"

    def test_auto_selects_pylint_as_fallback(self):
        def avail(b):
            return b == "pylint"

        with patch.object(DefaultLinter, "_check_backend_available", side_effect=avail):
            linter = DefaultLinter(backend="auto")
        assert linter._detected_backend == "pylint"

    def test_auto_none_if_nothing_available(self):
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=False
        ):
            linter = DefaultLinter(backend="auto")
        assert linter._detected_backend is None

    def test_explicit_backend_available(self):
        with patch.object(DefaultLinter, "_check_backend_available", return_value=True):
            linter = DefaultLinter(backend="ruff")
        assert linter._detected_backend == "ruff"

    def test_explicit_backend_unavailable(self):
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=False
        ):
            linter = DefaultLinter(backend="ruff")
        assert linter._detected_backend is None


# ---------------------------------------------------------------------------
# DefaultLinter — lint() cache hit path
# ---------------------------------------------------------------------------


class TestDefaultLinterCacheHit:
    """Test cache hit path in lint() (lines 208-211)."""

    def test_lint_cache_hit_returns_cached_result(self):
        """Second lint call with same content returns cached result (cache hit)."""
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=True
        ):
            linter = DefaultLinter(backend="ruff", enable_cache=True, cache_ttl=300)
        with patch.object(linter, "_lint_content", return_value=LintResult([], [])):
            r1 = linter.lint(content="x = 1")
            r2 = linter.lint(content="x = 1")
        assert r1 is r2
        stats = linter.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1


# ---------------------------------------------------------------------------
# DefaultLinter — _lint_file (LSP and ruff paths)
# ---------------------------------------------------------------------------


class TestDefaultLinterLintFile:
    """Test _lint_file with LSP and ruff backends."""

    def test_lint_file_ruff_path(self):
        """_lint_file uses ruff when backend is ruff and file is .py."""
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=True
        ):
            linter = DefaultLinter(backend="ruff")
        with (
            patch(
                "backend.utils.lsp_client.get_lsp_client",
                return_value=MagicMock(
                    query=MagicMock(
                        return_value=MagicMock(
                            available=False, error=True, locations=[]
                        )
                    )
                ),
            ),
            patch.object(linter, "_lint_with_ruff") as mock_ruff,
        ):
            mock_ruff.return_value = LintResult([], [])
            result = linter.lint(file_path="test.py")
        mock_ruff.assert_called_once_with(file_path="test.py")
        assert result.errors == []
        assert result.warnings == []

    def test_lint_file_lsp_returns_errors(self):
        """_lint_file uses LSP when available and returns errors."""
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=True
        ):
            linter = DefaultLinter(backend="ruff")
        mock_loc = MagicMock()
        mock_loc.line = 5
        mock_loc.column = 3
        with patch(
            "backend.utils.lsp_client.get_lsp_client",
            return_value=MagicMock(
                query=MagicMock(
                    return_value=MagicMock(
                        available=True, error=False, locations=[mock_loc]
                    )
                )
            ),
        ):
            result = linter.lint(file_path="test.py")
        assert len(result.errors) == 1
        assert result.errors[0].line == 5
        assert result.errors[0].column == 3
        assert result.errors[0].message == "LSP Diagnostic"

    def test_lint_file_non_py_returns_empty(self):
        """_lint_file returns empty for non-.py files."""
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=True
        ):
            linter = DefaultLinter(backend="ruff")
        with patch(
            "backend.utils.lsp_client.get_lsp_client",
            return_value=MagicMock(
                query=MagicMock(
                    return_value=MagicMock(
                        available=False, error=True, locations=[]
                    )
                )
            ),
        ):
            result = linter.lint(file_path="test.txt")
        assert result.errors == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# DefaultLinter — _lint_content fallback
# ---------------------------------------------------------------------------


class TestDefaultLinterLintContent:
    """Test _lint_content with unsupported backend (line 351 fallback)."""

    def test_lint_content_unsupported_backend_returns_empty(self):
        """When backend is neither ruff nor pylint, returns empty LintResult."""
        with patch.object(
            DefaultLinter, "_check_backend_available", return_value=True
        ):
            linter = DefaultLinter(backend="tree-sitter")
        # tree-sitter is not handled in _lint_content, falls through to line 351
        result = linter.lint(content="x = 1")
        assert result.errors == []
        assert result.warnings == []
