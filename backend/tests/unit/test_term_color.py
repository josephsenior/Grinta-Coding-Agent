"""Tests for backend.utils.term_color — Terminal color helpers."""

from __future__ import annotations

import pytest

from backend.utils.term_color import TermColor, colorize


class TestTermColorEnum:
    """Tests for the TermColor enum values."""

    def test_warning_is_yellow(self):
        assert TermColor.WARNING.value == "yellow"

    def test_success_is_green(self):
        assert TermColor.SUCCESS.value == "green"

    def test_error_is_red(self):
        assert TermColor.ERROR.value == "red"

    def test_info_is_blue(self):
        assert TermColor.INFO.value == "blue"

    def test_grey_is_dark_grey(self):
        assert TermColor.GREY.value == "dark_grey"

    def test_all_members(self):
        names = {m.name for m in TermColor}
        assert names == {"WARNING", "SUCCESS", "ERROR", "INFO", "GREY"}


class TestColorize:
    """Tests for the colorize function."""

    def test_returns_string(self):
        result = colorize("hello")
        assert isinstance(result, str)

    def test_default_color_is_warning(self):
        result = colorize("test")
        expected = colorize("test", TermColor.WARNING)
        assert result == expected

    def test_each_color_uses_correct_value(self):
        """Each TermColor variant passes the right color string to termcolor.colored."""
        from unittest.mock import patch

        for color in TermColor:
            with patch("backend.utils.term_color.colored") as mock_colored:
                mock_colored.return_value = "x"
                colorize("text", color)
                mock_colored.assert_called_once_with("text", color.value)

    def test_contains_original_text(self):
        result = colorize("hello world", TermColor.SUCCESS)
        assert "hello world" in result

    def test_empty_string(self):
        result = colorize("", TermColor.ERROR)
        assert isinstance(result, str)

    def test_text_with_special_characters(self):
        result = colorize("line1\nline2\ttab", TermColor.INFO)
        assert "line1" in result
        assert "line2" in result
