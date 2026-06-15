"""Unit tests for syntax_check helper utilities."""

from __future__ import annotations

from types import SimpleNamespace

from backend.utils.syntax_check import (
    SyntaxCheckResult,
    _first_line_column,
    _json_check,
    _python_compile_check,
    _toml_check,
    collect_tree_sitter_syntax_errors,
)


def test_syntax_check_result_ok_and_legacy_tuple() -> None:
    passed = SyntaxCheckResult(path='a.py', status='passed')
    failed = SyntaxCheckResult(path='a.py', status='failed', detail='bad')
    skipped = SyntaxCheckResult(path='a.py', status='skipped')
    assert passed.ok is True
    assert failed.ok is False
    assert passed.as_legacy_tuple() == (True, '')
    assert failed.as_legacy_tuple() == (False, 'bad')
    assert skipped.as_legacy_tuple() is None


def test_first_line_column_parses_detail() -> None:
    assert _first_line_column('line 12:4 syntax error') == (12, 4)
    assert _first_line_column('no line info') == (None, None)


def test_python_compile_check_pass_and_fail() -> None:
    ok = _python_compile_check('ok.py', 'x = 1\n')
    assert ok.status == 'passed'
    bad = _python_compile_check('bad.py', 'def broken(:\n')
    assert bad.status == 'failed'
    assert bad.line is not None


def test_json_and_toml_checks() -> None:
    assert _json_check('data.json', 'json', '{"a": 1}').status == 'passed'
    assert _json_check('data.json', 'json', '{bad').status == 'failed'
    assert _toml_check('pyproject.toml', 'toml', 'name = "x"\n').status == 'passed'
    assert _toml_check('pyproject.toml', 'toml', 'name =').status == 'failed'


def test_collect_tree_sitter_syntax_errors_walks_nodes() -> None:
    error_node = SimpleNamespace(
        type='ERROR',
        is_missing=False,
        start_point=(0, 0),
        start_byte=0,
        end_byte=3,
        children=[],
    )
    root = SimpleNamespace(
        type='module',
        is_missing=False,
        start_point=(0, 0),
        start_byte=0,
        end_byte=3,
        children=[error_node],
    )
    errors = collect_tree_sitter_syntax_errors(root, b'bad', max_errors=3)
    assert len(errors) == 1
    assert 'line 1:1' in errors[0]
