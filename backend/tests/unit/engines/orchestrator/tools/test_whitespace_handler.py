"""Tests for backend.engines.orchestrator.tools.whitespace_handler — indentation and whitespace utilities."""

from backend.engines.orchestrator.tools.whitespace_handler import (
    IndentConfig,
    IndentStyle,
    WhitespaceHandler,
)


class TestIndentStyle:
    """Tests for IndentStyle enum."""

    def test_spaces_variant(self):
        """Test SPACES variant exists."""
        assert IndentStyle.SPACES.value == "spaces"

    def test_tabs_variant(self):
        """Test TABS variant exists."""
        assert IndentStyle.TABS.value == "tabs"

    def test_mixed_variant(self):
        """Test MIXED variant exists."""
        assert IndentStyle.MIXED.value == "mixed"


class TestIndentConfig:
    """Tests for IndentConfig dataclass."""

    def test_create_indent_config(self):
        """Test creating IndentConfig instance."""
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        assert config.style == IndentStyle.SPACES
        assert config.size == 4
        assert config.line_ending == "\n"

    def test_indent_config_with_tabs(self):
        """Test IndentConfig with tabs."""
        config = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        assert config.style == IndentStyle.TABS
        assert config.size == 1

    def test_indent_config_with_crlf(self):
        """Test IndentConfig with CRLF line endings."""
        config = IndentConfig(style=IndentStyle.SPACES, size=2, line_ending="\r\n")
        assert config.line_ending == "\r\n"


class TestDetectLineEnding:
    """Tests for _detect_line_ending method."""

    def test_detect_unix_line_ending(self):
        """Test detecting Unix line endings."""
        code = "line1\nline2\nline3"
        result = WhitespaceHandler._detect_line_ending(code)
        assert result == "\n"

    def test_detect_windows_line_ending(self):
        """Test detecting Windows line endings."""
        code = "line1\r\nline2\r\nline3"
        result = WhitespaceHandler._detect_line_ending(code)
        assert result == "\r\n"

    def test_mixed_line_endings(self):
        """Test mixed line endings defaults to CRLF if present."""
        code = "line1\r\nline2\nline3"
        result = WhitespaceHandler._detect_line_ending(code)
        assert result == "\r\n"

    def test_no_line_endings(self):
        """Test single line with no line endings."""
        code = "single line"
        result = WhitespaceHandler._detect_line_ending(code)
        assert result == "\n"


class TestDetectIndent:
    """Tests for detect_indent method."""

    def test_detect_spaces_indent(self):
        """Test detecting space indentation."""
        code = "def foo():\n    pass\n    return"
        config = WhitespaceHandler.detect_indent(code)
        assert config.style == IndentStyle.SPACES
        assert config.size == 4

    def test_detect_tabs_indent(self):
        """Test detecting tab indentation."""
        code = "def foo():\n\tpass\n\treturn"
        config = WhitespaceHandler.detect_indent(code)
        assert config.style == IndentStyle.TABS
        assert config.size == 1

    def test_detect_two_space_indent(self):
        """Test detecting 2-space indentation."""
        code = "if true:\n  x = 1\n  y = 2\n    z = 3"
        config = WhitespaceHandler.detect_indent(code)
        assert config.style == IndentStyle.SPACES
        assert config.size == 2

    def test_detect_with_no_indentation(self):
        """Test detecting with no indented lines."""
        code = "x = 1\ny = 2\nz = 3"
        config = WhitespaceHandler.detect_indent(code)
        assert config.style == IndentStyle.SPACES
        assert config.size == 4  # Default

    def test_detect_with_language_hint_python(self):
        """Test detection with Python language hint."""
        code = "x = 1"
        config = WhitespaceHandler.detect_indent(code, language="python")
        assert config.style == IndentStyle.SPACES
        assert config.size == 4

    def test_detect_with_language_hint_go(self):
        """Test detection with Go language hint."""
        code = "x := 1"
        config = WhitespaceHandler.detect_indent(code, language="go")
        assert config.style == IndentStyle.TABS
        assert config.size == 1

    def test_detect_line_endings_preserved(self):
        """Test line endings are detected correctly."""
        code = "x = 1\r\ny = 2"
        config = WhitespaceHandler.detect_indent(code)
        assert config.line_ending == "\r\n"


class TestNormalizeIndent:
    """Tests for normalize_indent method."""

    def test_normalize_tabs_to_spaces(self):
        """Test converting tabs to spaces."""
        code = "def foo():\n\tpass"
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "\t" not in result
        assert "    pass" in result

    def test_normalize_spaces_to_tabs(self):
        """Test converting spaces to tabs."""
        code = "def foo():\n    pass"
        target = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "    " not in result
        assert "\tpass" in result

    def test_normalize_4_spaces_to_2_spaces(self):
        """Test converting 4-space to 2-space indentation."""
        code = "if true:\n    x = 1\n        y = 2"
        target = IndentConfig(style=IndentStyle.SPACES, size=2, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        lines = result.split("\n")
        assert lines[1] == "  x = 1"
        assert lines[2] == "    y = 2"

    def test_normalize_preserves_content(self):
        """Test normalization preserves line content."""
        code = "def foo():\n    return 42"
        target = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "return 42" in result

    def test_normalize_empty_code(self):
        """Test normalizing empty code."""
        result = WhitespaceHandler.normalize_indent("")
        assert result == ""

    def test_normalize_no_change_needed(self):
        """Test normalizing code that already matches target."""
        code = "def foo():\n    pass"
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert result == code

    def test_normalize_line_endings(self):
        """Test normalizing line endings."""
        code = "line1\nline2"
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\r\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "\r\n" in result


class TestAutoIndentBlock:
    """Tests for auto_indent_block method."""

    def test_auto_indent_with_zero_base(self):
        """Test auto-indenting with zero base indentation."""
        code_block = "x = 1\ny = 2"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code_block, 0, config)
        assert result == code_block

    def test_auto_indent_with_one_level(self):
        """Test auto-indenting with one level."""
        code_block = "x = 1\ny = 2"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code_block, 1, config)
        lines = result.split("\n")
        assert lines[0] == "    x = 1"
        assert lines[1] == "    y = 2"

    def test_auto_indent_with_tabs(self):
        """Test auto-indenting with tabs."""
        code_block = "pass"
        config = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code_block, 2, config)
        assert result == "\t\tpass"

    def test_auto_indent_preserves_blank_lines(self):
        """Test auto-indent preserves blank lines."""
        code_block = "x = 1\n\ny = 2"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code_block, 1, config)
        lines = result.split("\n")
        assert lines[0] == "    x = 1"
        assert lines[1] == ""
        assert lines[2] == "    y = 2"

    def test_auto_indent_multiple_levels(self):
        """Test auto-indenting with multiple levels."""
        code_block = "if True:\n    pass"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code_block, 1, config)
        lines = result.split("\n")
        assert lines[0].startswith("    if")
        assert lines[1].startswith("        pass")


class TestGetLineIndent:
    """Tests for get_line_indent method."""

    def test_get_indent_no_whitespace(self):
        """Test getting indent of line with no leading whitespace."""
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.get_line_indent("x = 1", config)
        assert result == 0

    def test_get_indent_one_level_spaces(self):
        """Test getting indent of line with one level."""
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.get_line_indent("    x = 1", config)
        assert result == 1

    def test_get_indent_two_levels_spaces(self):
        """Test getting indent of line with two levels."""
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.get_line_indent("        x = 1", config)
        assert result == 2

    def test_get_indent_with_tabs(self):
        """Test getting indent with tabs."""
        config = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        result = WhitespaceHandler.get_line_indent("\t\tx = 1", config)
        assert result == 2

    def test_get_indent_empty_line(self):
        """Test getting indent of empty line."""
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.get_line_indent("", config)
        assert result == 0


class TestPreserveRelativeIndent:
    """Tests for preserve_relative_indent method."""

    def test_preserve_relative_indent_simple(self):
        """Test preserving relative indentation."""
        code_block = "if True:\n    pass\n    return"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.preserve_relative_indent(code_block, 1, config)
        lines = result.split("\n")
        assert lines[0] == "    if True:"
        assert lines[1] == "        pass"
        assert lines[2] == "        return"

    def test_preserve_relative_indent_nested(self):
        """Test preserving nested indentation."""
        code_block = "if True:\n    if False:\n        pass"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.preserve_relative_indent(code_block, 0, config)
        lines = result.split("\n")
        assert lines[0] == "if True:"
        assert lines[1] == "    if False:"
        assert lines[2] == "        pass"

    def test_preserve_relative_indent_empty_lines(self):
        """Test preserving indentation with empty lines."""
        code_block = "x = 1\n\n    y = 2"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.preserve_relative_indent(code_block, 1, config)
        lines = result.split("\n")
        assert lines[0] == "    x = 1"
        assert lines[1] == ""
        assert lines[2] == "        y = 2"

    def test_preserve_relative_indent_empty_code(self):
        """Test preserving indentation with empty code."""
        result = WhitespaceHandler.preserve_relative_indent("", 1)
        assert result == ""


class TestStripTrailingWhitespace:
    """Tests for strip_trailing_whitespace method."""

    def test_strip_trailing_spaces(self):
        """Test stripping trailing spaces."""
        code = "x = 1   \ny = 2  "
        result = WhitespaceHandler.strip_trailing_whitespace(code)
        lines = result.split("\n")
        assert lines[0] == "x = 1"
        assert lines[1] == "y = 2"

    def test_strip_trailing_tabs(self):
        """Test stripping trailing tabs."""
        code = "x = 1\t\t\ny = 2"
        result = WhitespaceHandler.strip_trailing_whitespace(code)
        lines = result.split("\n")
        assert lines[0] == "x = 1"

    def test_strip_preserves_content(self):
        """Test stripping preserves line content."""
        code = "x = 1  "
        result = WhitespaceHandler.strip_trailing_whitespace(code)
        assert result == "x = 1"

    def test_strip_no_trailing_whitespace(self):
        """Test stripping when no trailing whitespace."""
        code = "x = 1\ny = 2"
        result = WhitespaceHandler.strip_trailing_whitespace(code)
        assert result == code


class TestEnsureFinalNewline:
    """Tests for ensure_final_newline method."""

    def test_add_final_newline(self):
        """Test adding final newline when missing."""
        code = "x = 1"
        result = WhitespaceHandler.ensure_final_newline(code)
        assert result == "x = 1\n"

    def test_preserve_single_newline(self):
        """Test preserving single newline."""
        code = "x = 1\n"
        result = WhitespaceHandler.ensure_final_newline(code)
        assert result == "x = 1\n"

    def test_remove_multiple_newlines(self):
        """Test removing multiple trailing newlines."""
        code = "x = 1\n\n\n"
        result = WhitespaceHandler.ensure_final_newline(code)
        assert result == "x = 1\n"

    def test_empty_string(self):
        """Test with empty string."""
        result = WhitespaceHandler.ensure_final_newline("")
        assert result == "\n"


class TestCleanWhitespace:
    """Tests for clean_whitespace method."""

    def test_clean_removes_trailing_whitespace(self):
        """Test cleaning removes trailing whitespace."""
        code = "x = 1  \ny = 2  "
        result = WhitespaceHandler.clean_whitespace(code)
        assert "  \n" not in result

    def test_clean_ensures_final_newline(self):
        """Test cleaning ensures final newline."""
        code = "x = 1"
        result = WhitespaceHandler.clean_whitespace(code)
        assert result.endswith("\n")

    def test_clean_removes_excessive_blank_lines(self):
        """Test cleaning removes excessive blank lines."""
        code = "x = 1\n\n\n\n\ny = 2"
        result = WhitespaceHandler.clean_whitespace(code)
        # Max 2 consecutive blank lines (3 newlines)
        assert "\n\n\n\n" not in result

    def test_clean_normalizes_indentation(self):
        """Test cleaning normalizes indentation."""
        code = "def foo():\n\tpass"
        result = WhitespaceHandler.clean_whitespace(code, language="python")
        assert result.endswith("\n")

    def test_clean_comprehensive(self):
        """Test comprehensive cleaning."""
        code = "def foo():  \n\t\tpass  \n\n\n\n\nx = 1"
        result = WhitespaceHandler.clean_whitespace(code, language="python")
        assert "  \n" not in result
        assert result.endswith("\n")
        assert "\n\n\n\n" not in result


class TestWhitespaceIntegration:
    """Integration tests for WhitespaceHandler."""

    def test_full_workflow_tabs_to_spaces(self):
        """Test full workflow: detect, normalize, clean."""
        code = "def foo():\n\tpass\n\treturn 42\t"

        # Detect current style
        current = WhitespaceHandler.detect_indent(code)
        assert current.style == IndentStyle.TABS

        # Normalize to spaces
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        normalized = WhitespaceHandler.normalize_indent(code, target)

        # Clean up
        cleaned = WhitespaceHandler.clean_whitespace(normalized)

        assert "\t" not in cleaned
        assert cleaned.endswith("\n")
        assert "    pass" in cleaned

    def test_auto_indent_and_clean(self):
        """Test auto-indenting and cleaning."""
        code_block = "x = 1\ny = 2"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")

        indented = WhitespaceHandler.auto_indent_block(code_block, 1, config)
        cleaned = WhitespaceHandler.clean_whitespace(indented, config)

        assert "    x = 1" in cleaned
        assert cleaned.endswith("\n")
