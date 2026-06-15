"""Unit tests for TUI unified-diff row helpers."""

from __future__ import annotations

from backend.cli.tui.helpers import (
    _delete_rows,
    _encode_diff_view_from_contents,
    _equal_rows,
    _insert_rows,
    _numbered_diff_line,
    _replace_rows,
    _split_diff_opcode_rows,
)


def test_numbered_diff_line_prefixes() -> None:
    assert _numbered_diff_line('add', 1, 'line', 2) == '+ 1|line'
    assert _numbered_diff_line('rem', 3, 'gone', 2) == '- 3|gone'
    assert _numbered_diff_line('ctx', 4, 'same', 2) == '  4|same'


def test_equal_rows_pairs_context_lines() -> None:
    old_lines = ['a', 'b']
    new_lines = ['a', 'b']
    rows = _equal_rows(old_lines, new_lines, 0, 2, 0, 2, pad=2)
    assert len(rows) == 2
    assert rows[0][2] == 'ctx'


def test_delete_and_insert_rows() -> None:
    old_lines = ['remove-me']
    new_lines: list[str] = []
    deleted = _delete_rows(old_lines, new_lines, 0, 1, 0, 0, pad=2)
    assert deleted[0][0].startswith('-')
    inserted = _insert_rows([], ['added'], 0, 0, 0, 1, pad=2)
    assert inserted[0][1].startswith('+')


def test_replace_rows_handles_mismatched_counts() -> None:
    old_lines = ['old1', 'old2']
    new_lines = ['new1']
    rows = _replace_rows(old_lines, new_lines, 0, 2, 0, 1, pad=2)
    assert len(rows) == 2
    assert rows[0][0].startswith('-')
    assert rows[0][1].startswith('+')


def test_split_diff_opcode_rows_dispatches() -> None:
    old_lines = ['x']
    new_lines = ['y']
    rows = _split_diff_opcode_rows('replace', old_lines, new_lines, 0, 1, 0, 1, pad=2)
    assert rows
    assert _split_diff_opcode_rows('unknown', old_lines, new_lines, 0, 1, 0, 1, pad=2) == []


def test_encode_diff_view_from_contents() -> None:
    payload = _encode_diff_view_from_contents('a', 'b', path='file.py')
    assert payload is not None
    assert 'grinta-diff-view' in payload
    assert _encode_diff_view_from_contents('same', 'same') is None
