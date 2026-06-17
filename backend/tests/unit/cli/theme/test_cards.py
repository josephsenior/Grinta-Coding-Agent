"""Unit tests for shared TUI card theme tokens."""

from __future__ import annotations

from backend.cli.theme.cards import file_change_kind_class, footer_color_for_exit_code


def test_file_change_kind_class() -> None:
    assert file_change_kind_class('+3') == '-create'
    assert file_change_kind_class('+1 -1') == '-edit'
    assert file_change_kind_class('-2') == '-edit'
    assert file_change_kind_class(None) == ''
    assert file_change_kind_class('') == ''


def test_footer_color_for_exit_code() -> None:
    assert footer_color_for_exit_code(0) == '#54efae'
    assert footer_color_for_exit_code(1) == '#fd8383'
    assert footer_color_for_exit_code(None) == '#8f9fc1'
