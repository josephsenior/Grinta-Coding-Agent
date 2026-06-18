"""Unit tests for backend.cli.display.text_truncation."""

from __future__ import annotations

from backend.cli.display.text_truncation import shorten_middle, shorten_path, truncate_line


def test_shorten_middle_preserves_head_and_tail() -> None:
    text = 'a' * 30 + 'middle' + 'b' * 30
    shortened = shorten_middle(text, max_len=20)
    assert shortened.startswith('a')
    assert shortened.endswith('b')
    assert '…' in shortened
    assert shorten_middle('short', max_len=20) == 'short'


def test_shorten_path_keeps_tail() -> None:
    path = 'very/long/path/to/module.py'
    shortened = shorten_path(path, max_len=15)
    assert shortened.endswith('module.py')
    assert shortened.startswith('…')
    assert shorten_path('a.py', max_len=10) == 'a.py'


def test_truncate_line_word_boundary() -> None:
    label = 'run integration tests for authentication module'
    truncated = truncate_line(label, max_len=30)
    assert truncated.endswith('…')
    assert len(truncated) <= 30
    assert truncate_line('', max_len=10) == ''
    assert truncate_line('hi', max_len=0) == 'hi'
