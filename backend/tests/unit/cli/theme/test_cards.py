"""Unit tests for shared TUI card theme tokens."""

from __future__ import annotations

from backend.cli.theme.cards import footer_color_for_exit_code


def test_footer_color_for_exit_code() -> None:
    assert footer_color_for_exit_code(0) == '#54efae'
    assert footer_color_for_exit_code(1) == '#fd8383'
    assert footer_color_for_exit_code(None) == '#8f9fc1'
