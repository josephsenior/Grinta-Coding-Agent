"""Tests for backend.validation.code_quality.linter — LintError, LintResult, DefaultLinter."""

# pylint: disable=no-member,protected-access,wrong-import-order,use-implicit-booleaness-not-comparison

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.validation.code_quality.linter import DefaultLinter, LintError, LintResult

DefaultLinterAny: Any = DefaultLinter


def default_linter_any(*args: Any, **kwargs: Any) -> Any:
    return DefaultLinter(*args, **kwargs)


# ── LintError ─────────────────────────────────────────────────────────


class TestLintError:
    def test_visualize_line_only(self):
        err = LintError(line=10, column=None, message='bad thing')
        assert err.visualize() == 'line 10: bad thing'

    def test_visualize_line_and_column(self):
        err = LintError(line=10, column=5, message='bad thing')
        assert 'column 5' in err.visualize()

    def test_visualize_with_code(self):
        err = LintError(line=10, column=None, message='bad', code='E001')
        assert '[E001]' in err.visualize()

    def test_default_severity(self):
        err = LintError(line=1, column=None, message='x')
        assert err.severity == 'error'


# ── LintResult ────────────────────────────────────────────────────────


class TestLintResult:
    def test_separates_errors_and_warnings(self):
        e1 = LintError(line=1, column=None, message='err', severity='error')
        w1 = LintError(line=2, column=None, message='warn', severity='warning')
        result = LintResult(errors=[e1, w1], warnings=[])
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert result.errors[0].severity == 'error'
        assert result.warnings[0].severity == 'warning'

    def test_empty_results(self):
        result = LintResult(errors=[], warnings=[])
        assert not result.errors
        assert not result.warnings

    def test_duplicates_in_both_lists_separated(self):
        e1 = LintError(line=1, column=None, message='x', severity='error')
        w1 = LintError(line=2, column=None, message='y', severity='warning')
        result = LintResult(errors=[e1], warnings=[w1])
        assert len(result.errors) == 1
        assert len(result.warnings) == 1


# ── DefaultLinter initialization ──────────────────────────────────────


class TestDefaultLinterInit:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=False)
    def test_no_backend_available(self, mock_check):
        linter = default_linter_any(backend='auto')
        assert linter._detected_backend is None

    @patch.object(
        DefaultLinter,
        '_check_backend_available',
        side_effect=lambda b: b == 'tree-sitter',
    )
    def test_auto_detects_tree_sitter(self, mock_check):
        linter = default_linter_any(backend='auto')
        assert linter._detected_backend == 'tree-sitter'

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_explicit_backend(self, mock_check):
        linter = default_linter_any(backend='tree-sitter')
        assert linter._detected_backend == 'tree-sitter'

    @patch.object(DefaultLinter, '_check_backend_available', return_value=False)
    def test_explicit_backend_unavailable(self, mock_check):
        linter = default_linter_any(backend='tree-sitter')
        assert linter._detected_backend is None


# ── Cache logic ───────────────────────────────────────────────────────


class TestDefaultLinterCache:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=False)
    def test_no_backend_returns_empty(self, _):
        linter = default_linter_any()
        result = linter.lint(content='x = 1')
        assert not result.errors
        assert not result.warnings

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_cache_hit(self, _):
        linter = default_linter_any(backend='tree-sitter')
        expected = LintResult(errors=[], warnings=[])
        key = 'lint:content:abc:def'
        linter._cache[key] = (expected, time.time())

        # Mock _get_cache_key to return matching key
        with patch.object(linter, '_get_cache_key', return_value=key):
            result = linter.lint(content='x = 1')
        assert result is expected
        assert linter._cache_hits == 1

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_cache_hit_uses_cached_result(self, _):
        linter = default_linter_any(backend='tree-sitter')
        expected = LintResult(errors=[LintError(1, None, 'x')], warnings=[])
        key = 'lint:content:hit:cfg'

        with (
            patch.object(linter, '_get_cache_key', return_value=key),
            patch.object(linter, '_get_from_cache', return_value=expected),
        ):
            result = linter.lint(content='x = 1')

        assert result is expected
        assert linter._cache_hits == 1

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_cache_miss_increments_counter(self, _):
        linter = default_linter_any(backend='tree-sitter')
        with patch.object(linter, '_lint_content', return_value=LintResult([], [])):
            linter.lint(content='x = 1')
        assert linter._cache_misses == 1

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_cache_eviction(self, _):
        linter = default_linter_any(backend='tree-sitter', max_cache_size=2)
        linter._cache['k1'] = (LintResult([], []), time.time())
        linter._cache['k2'] = (LintResult([], []), time.time())
        # Add a third entry
        linter._set_cache('k3', LintResult([], []))
        assert len(linter._cache) == 2
        assert 'k1' not in linter._cache  # oldest evicted

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_expired_cache_entry(self, _):
        linter = default_linter_any(backend='tree-sitter', cache_ttl=1)
        linter._cache['key'] = (LintResult([], []), time.time() - 10)
        result = linter._get_from_cache('key')
        assert result is None
        assert 'key' not in linter._cache

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_clear_cache(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._cache['k1'] = (LintResult([], []), time.time())
        linter._cache_hits = 5
        linter._cache_misses = 3
        linter.clear_cache()
        assert not linter._cache
        assert linter._cache_hits == 0

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_get_cache_stats(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._cache_hits = 10
        linter._cache_misses = 5
        stats = linter.get_cache_stats()
        assert stats['hits'] == 10
        assert stats['misses'] == 5
        assert '66.7%' in stats['hit_rate']


# ── _get_cache_key ────────────────────────────────────────────────────


class TestGetCacheKey:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_content_based_key(self, _):
        linter = default_linter_any(backend='tree-sitter')
        key = linter._get_cache_key(None, 'hello world')
        assert key is not None
        assert 'lint:content:' in key

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_no_input_returns_none(self, _):
        linter = default_linter_any(backend='tree-sitter')
        key = linter._get_cache_key(None, None)
        assert key is None

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_file_path_key(self, _, tmp_path):
        f = tmp_path / 'test.py'
        f.write_text('x = 1')
        linter = default_linter_any(backend='tree-sitter')
        key = linter._get_cache_key(str(f), None)
        assert key is not None
        assert 'lint:' in key

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_file_path_stat_oserror(self, _, tmp_path, monkeypatch):
        f = tmp_path / 'test.py'
        f.write_text('x = 1')
        linter = default_linter_any(backend='tree-sitter')

        monkeypatch.setattr(Path, 'exists', lambda self: True)

        def _raise_oserror(*_args, **_kwargs):
            raise OSError('stat failed')

        monkeypatch.setattr(Path, 'stat', _raise_oserror)

        key = linter._get_cache_key(str(f), None)
        assert key is None


# ── _hash_config ──────────────────────────────────────────────────────


class TestHashConfig:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_deterministic(self, _):
        linter = default_linter_any(backend='tree-sitter')
        assert linter._hash_config() == linter._hash_config()

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_different_config_path(self, _):
        linter1 = default_linter_any(backend='tree-sitter', config_path=None)
        linter2 = default_linter_any(
            backend='tree-sitter', config_path='/tmp/ruff.toml'
        )
        assert linter1._hash_config() != linter2._hash_config()


# ── lint_file_diff ────────────────────────────────────────────────────


class TestLintFileDiff:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_delegates_to_lint(self, _):
        linter = default_linter_any(backend='tree-sitter')
        expected = LintResult(
            errors=[LintError(line=1, column=None, message='err')],
            warnings=[
                LintError(line=2, column=None, message='warn', severity='warning')
            ],
        )
        with patch.object(linter, 'lint', return_value=expected):
            issues = linter.lint_file_diff('orig.py', 'updated.py')
        assert len(issues) == 2


# ── _lint_with_ruff / _lint_with_pylint removed (linter uses LSP only) ───
# Tests below are skipped; backend uses tree-sitter + LSP, not ruff/pylint.


@pytest.mark.skip(reason='ruff backend removed; linter uses LSP only')
class TestLintWithRuff:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_parses_ruff_json_output(self, _):
        linter = default_linter_any(backend='tree-sitter')
        ruff_output = [
            {
                'location': {'row': 5, 'column': 1},
                'code': 'E302',
                'message': 'expected 2 blank lines',
            },
            {
                'location': {'row': 10, 'column': 3},
                'code': 'W291',
                'message': 'trailing whitespace',
            },
        ]
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = json.dumps(ruff_output)
        mock_result.stderr = ''

        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            return_value=mock_result,
        ):
            result = linter._lint_with_ruff('test.py')
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert result.errors[0].line == 5

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_ruff_timeout(self, _):
        linter = default_linter_any(backend='tree-sitter')
        import subprocess

        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=subprocess.TimeoutExpired('ruff', 30),
        ):
            result = linter._lint_with_ruff('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_ruff_not_found(self, _):
        linter = default_linter_any(backend='tree-sitter')
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=FileNotFoundError,
        ):
            result = linter._lint_with_ruff('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_ruff_bad_returncode(self, _):
        linter = default_linter_any(backend='tree-sitter')
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stderr = 'crash'
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            return_value=mock_result,
        ):
            result = linter._lint_with_ruff('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_ruff_invalid_json(self, _):
        linter = default_linter_any(backend='tree-sitter')
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = 'not json'
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            return_value=mock_result,
        ):
            result = linter._lint_with_ruff('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_ruff_uses_config_path(self, _):
        linter = default_linter_any(backend='tree-sitter', config_path='/tmp/ruff.toml')
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '[]'
        mock_result.stderr = ''
        captured = {}

        def fake_run(cmd, **_kwargs):
            captured['cmd'] = cmd
            return mock_result

        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=fake_run,
        ):
            result = linter._lint_with_ruff('test.py')

        assert result.errors == []
        assert '--config' in captured['cmd']
        assert '/tmp/ruff.toml' in captured['cmd']

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_ruff_generic_exception(self, _):
        linter = default_linter_any(backend='tree-sitter')
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=RuntimeError('boom'),
        ):
            result = linter._lint_with_ruff('test.py')
        assert result.errors == []


@pytest.mark.skip(reason='pylint backend removed; linter uses LSP only')
class TestLintWithPylint:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_parses_pylint_json_output(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._detected_backend = 'pylint'
        pylint_output = [
            {
                'line': 3,
                'column': 0,
                'message': 'Missing module docstring',
                'message-id': 'C0114',
                'type': 'convention',
            },
            {
                'line': 8,
                'column': 4,
                'message': 'Undefined variable',
                'message-id': 'E0602',
                'type': 'error',
            },
        ]
        mock_result = MagicMock()
        mock_result.returncode = 4
        mock_result.stdout = json.dumps(pylint_output)
        mock_result.stderr = ''

        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            return_value=mock_result,
        ):
            result = linter._lint_with_pylint('test.py')
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_pylint_timeout(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._detected_backend = 'pylint'
        import subprocess

        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=subprocess.TimeoutExpired('pylint', 60),
        ):
            result = linter._lint_with_pylint('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_pylint_invalid_json(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._detected_backend = 'pylint'
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = 'not json'
        mock_result.stderr = ''
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            return_value=mock_result,
        ):
            result = linter._lint_with_pylint('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_pylint_not_found(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._detected_backend = 'pylint'
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=FileNotFoundError,
        ):
            result = linter._lint_with_pylint('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_pylint_generic_exception(self, _):
        linter = default_linter_any(backend='tree-sitter')
        linter._detected_backend = 'pylint'
        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=RuntimeError('boom'),
        ):
            result = linter._lint_with_pylint('test.py')
        assert result.errors == []

    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_pylint_uses_config_path(self, _):
        linter = default_linter_any(backend='tree-sitter', config_path='/tmp/pylint.rc')
        linter._detected_backend = 'pylint'
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = '[]'
        mock_result.stderr = ''
        captured = {}

        def fake_run(cmd, **_kwargs):
            captured['cmd'] = cmd
            return mock_result

        with patch(
            'backend.validation.code_quality.linter.subprocess.run',
            side_effect=fake_run,
        ):
            result = linter._lint_with_pylint('test.py')

        assert result.errors == []
        assert '--rcfile' in captured['cmd']
        assert '/tmp/pylint.rc' in captured['cmd']


class TestLintContent:
    @patch.object(DefaultLinter, '_check_backend_available', return_value=True)
    def test_lint_content_returns_result(self, _, tmp_path):
        """_lint_content returns LintResult (currently empty; uses LSP path)."""
        linter = default_linter_any(backend='tree-sitter')
        result = linter._lint_content('x = 1', file_path=str(tmp_path / 'file.py'))
        assert isinstance(result, LintResult)
        assert result.errors == []
        assert result.warnings == []


# ── _check_backend_available ──────────────────────────────────────────


class TestCheckBackendAvailable:
    def test_tree_sitter_available(self):
        with patch.dict('sys.modules', {'tree_sitter': MagicMock()}):
            linter = DefaultLinter.__new__(DefaultLinter)
            assert linter._check_backend_available('tree-sitter') is True

    def test_tree_sitter_not_available(self):
        import builtins
        import sys

        real_import = builtins.__import__
        saved = sys.modules.pop('tree_sitter', None)

        def failing_import(name, *args, **kwargs):
            if name == 'tree_sitter':
                raise ImportError("No module named 'tree_sitter'")
            return real_import(name, *args, **kwargs)

        try:
            with patch.object(builtins, '__import__', failing_import):
                linter = DefaultLinter.__new__(DefaultLinter)
                assert linter._check_backend_available('tree-sitter') is False
        finally:
            if saved is not None:
                sys.modules['tree_sitter'] = saved

    def test_unknown_backend(self):
        linter = DefaultLinter.__new__(DefaultLinter)
        assert linter._check_backend_available('unknown') is False
