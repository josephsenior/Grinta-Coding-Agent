"""Tests for summarize._orient_path edge cases."""

from __future__ import annotations

from backend.cli.tool_display.summarize import _orient_path


def test_orient_path_empty_returns_empty() -> None:
    assert _orient_path('') == ''
    assert _orient_path(None) == ''


def test_orient_path_short_path_unchanged() -> None:
    assert _orient_path('src/main.py') == 'src/main.py'


def test_orient_path_long_path_uses_ellipsis() -> None:
    long_path = 'backend/' + 'nested/' * 10 + 'module.py'
    display = _orient_path(long_path, max_len=24)
    assert display.startswith('…')
    assert display.endswith('module.py')
