"""Tests for terminal color utilities."""

from backend.utils.term_color import TermColor, colorize


class TestTermColor:
    def test_warning_color(self):
        """Test WARNING color enum value."""
        assert TermColor.WARNING.value == "yellow"

    def test_success_color(self):
        """Test SUCCESS color enum value."""
        assert TermColor.SUCCESS.value == "green"

    def test_error_color(self):
        """Test ERROR color enum value."""
        assert TermColor.ERROR.value == "red"

    def test_info_color(self):
        """Test INFO color enum value."""
        assert TermColor.INFO.value == "blue"

    def test_grey_color(self):
        """Test GREY color enum value."""
        assert TermColor.GREY.value == "dark_grey"


class TestColorize:
    def test_colorize_default_warning(self):
        """Test colorize with default WARNING color."""
        result = colorize("test")
        # Result should be a string (colored output)
        assert isinstance(result, str)
        assert "test" in result

    def test_colorize_success(self):
        """Test colorize with SUCCESS color."""
        result = colorize("success", TermColor.SUCCESS)
        assert isinstance(result, str)
        assert "success" in result

    def test_colorize_error(self):
        """Test colorize with ERROR color."""
        result = colorize("error", TermColor.ERROR)
        assert isinstance(result, str)
        assert "error" in result

    def test_colorize_info(self):
        """Test colorize with INFO color."""
        result = colorize("info", TermColor.INFO)
        assert isinstance(result, str)
        assert "info" in result

    def test_colorize_grey(self):
        """Test colorize with GREY color."""
        result = colorize("grey text", TermColor.GREY)
        assert isinstance(result, str)
        assert "grey text" in result

    def test_colorize_empty_string(self):
        """Test colorize with empty string."""
        result = colorize("")
        assert isinstance(result, str)

    def test_colorize_multiline(self):
        """Test colorize with multiline text."""
        text = "line1\nline2\nline3"
        result = colorize(text, TermColor.WARNING)
        assert isinstance(result, str)
        assert "line1" in result

    def test_colorize_special_chars(self):
        """Test colorize with special characters."""
        text = "!@#$%^&*()"
        result = colorize(text, TermColor.SUCCESS)
        assert isinstance(result, str)
        assert "!@#$%^&*()" in result
