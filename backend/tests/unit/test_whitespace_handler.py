"""Tests for backend.engines.orchestrator.tools.whitespace_handler — WhitespaceHandler."""

from __future__ import annotations

import pytest

from backend.engines.orchestrator.tools.whitespace_handler import (
    IndentConfig,
    IndentStyle,
    WhitespaceHandler,
)


# ---------------------------------------------------------------------------
# detect_indent
# ---------------------------------------------------------------------------

class TestDetectIndent:
    """Tests for WhitespaceHandler.detect_indent."""

    def test_spaces_python_style(self):
        code = "def foo():\n    pass\n    return 1\n"
        cfg = WhitespaceHandler.detect_indent(code, "python")
        assert cfg.style == IndentStyle.SPACES
        assert cfg.size == 4

    def test_tabs_detected(self):
        code = "function foo() {\n\treturn 1;\n\tif (x) {\n\t\ty();\n\t}\n}\n"
        cfg = WhitespaceHandler.detect_indent(code)
        assert cfg.style == IndentStyle.TABS
        assert cfg.size == 1

    def test_two_space_indent(self):
        code = "function foo() {\n  return 1;\n  if (x) {\n    y();\n  }\n}\n"
        cfg = WhitespaceHandler.detect_indent(code, "javascript")
        assert cfg.style == IndentStyle.SPACES
        assert cfg.size == 2

    def test_no_indented_lines_uses_language_default(self):
        code = "hello\nworld\n"
        cfg = WhitespaceHandler.detect_indent(code, "python")
        assert cfg.style == IndentStyle.SPACES
        # Python default is 4
        assert cfg.size == 4

    def test_go_default_is_tabs(self):
        code = "package main\nfunc main() {}\n"
        cfg = WhitespaceHandler.detect_indent(code, "go")
        assert cfg.style == IndentStyle.TABS

    def test_line_ending_crlf(self):
        code = "hello\r\nworld\r\n"
        cfg = WhitespaceHandler.detect_indent(code)
        assert cfg.line_ending == "\r\n"

    def test_line_ending_lf(self):
        code = "hello\nworld\n"
        cfg = WhitespaceHandler.detect_indent(code)
        assert cfg.line_ending == "\n"


# ---------------------------------------------------------------------------
# normalize_indent
# ---------------------------------------------------------------------------

class TestNormalizeIndent:
    """Tests for WhitespaceHandler.normalize_indent."""

    def test_empty_code_unchanged(self):
        assert WhitespaceHandler.normalize_indent("") == ""

    def test_tabs_to_spaces(self):
        code = "def foo():\n\tpass\n\treturn 1\n"
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "\t" not in result
        assert "    pass" in result

    def test_spaces_to_tabs(self):
        code = "def foo():\n    pass\n    return 1\n"
        target = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "\tpass" in result

    def test_same_style_no_change(self):
        code = "def foo():\n    pass\n"
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert result == code

    def test_line_ending_conversion(self):
        code = "a\nb\n"
        target = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\r\n")
        result = WhitespaceHandler.normalize_indent(code, target)
        assert "\r\n" in result


# ---------------------------------------------------------------------------
# auto_indent_block
# ---------------------------------------------------------------------------

class TestAutoIndentBlock:
    """Tests for WhitespaceHandler.auto_indent_block."""

    def test_indent_to_level_2(self):
        code = "x = 1\ny = 2\n"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code, base_indent=2, config=config)
        lines = result.split("\n")
        assert lines[0] == "        x = 1"  # 8 spaces
        assert lines[1] == "        y = 2"

    def test_blank_lines_stay_blank(self):
        code = "x = 1\n\ny = 2\n"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code, base_indent=1, config=config)
        lines = result.split("\n")
        assert lines[1] == ""  # blank line stays blank

    def test_tabs_indent(self):
        code = "x = 1\ny = 2"
        config = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        result = WhitespaceHandler.auto_indent_block(code, base_indent=3, config=config)
        assert result.startswith("\t\t\t")


# ---------------------------------------------------------------------------
# get_line_indent
# ---------------------------------------------------------------------------

class TestGetLineIndent:
    """Tests for WhitespaceHandler.get_line_indent."""

    def test_no_indent(self):
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        assert WhitespaceHandler.get_line_indent("hello", config) == 0

    def test_one_level(self):
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        assert WhitespaceHandler.get_line_indent("    hello", config) == 1

    def test_two_levels(self):
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        assert WhitespaceHandler.get_line_indent("        hello", config) == 2

    def test_tab_indent(self):
        config = IndentConfig(style=IndentStyle.TABS, size=1, line_ending="\n")
        assert WhitespaceHandler.get_line_indent("\t\thello", config) == 2

    def test_empty_line(self):
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        assert WhitespaceHandler.get_line_indent("", config) == 0


# ---------------------------------------------------------------------------
# preserve_relative_indent
# ---------------------------------------------------------------------------

class TestPreserveRelativeIndent:
    """Tests for WhitespaceHandler.preserve_relative_indent."""

    def test_empty_code(self):
        assert WhitespaceHandler.preserve_relative_indent("", 2) == ""

    def test_shift_to_new_base(self):
        code = "    x = 1\n        y = 2\n"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.preserve_relative_indent(code, new_base_indent=0, config=config)
        lines = result.strip().split("\n")
        assert lines[0] == "x = 1"
        assert lines[1] == "    y = 2"

    def test_increase_base_indent(self):
        # Both lines indented: min_indent=1, so relative is preserved
        code = "    x = 1\n        y = 2\n"
        config = IndentConfig(style=IndentStyle.SPACES, size=4, line_ending="\n")
        result = WhitespaceHandler.preserve_relative_indent(code, new_base_indent=2, config=config)
        lines = result.splitlines()
        assert lines[0] == "        x = 1"  # base=2 → 8 spaces
        assert lines[1] == "            y = 2"  # base=2 + relative=1 → 12 spaces


# ---------------------------------------------------------------------------
# strip_trailing_whitespace
# ---------------------------------------------------------------------------

class TestStripTrailingWhitespace:
    """Tests for WhitespaceHandler.strip_trailing_whitespace."""

    def test_removes_trailing_spaces(self):
        code = "hello   \nworld  \n"
        result = WhitespaceHandler.strip_trailing_whitespace(code)
        assert result == "hello\nworld\n"

    def test_preserves_leading_spaces(self):
        code = "    hello\n"
        result = WhitespaceHandler.strip_trailing_whitespace(code)
        assert result == "    hello\n"


# ---------------------------------------------------------------------------
# ensure_final_newline
# ---------------------------------------------------------------------------

class TestEnsureFinalNewline:
    """Tests for WhitespaceHandler.ensure_final_newline."""

    def test_adds_newline(self):
        assert WhitespaceHandler.ensure_final_newline("hello") == "hello\n"

    def test_already_has_newline(self):
        assert WhitespaceHandler.ensure_final_newline("hello\n") == "hello\n"

    def test_multiple_newlines_reduced(self):
        result = WhitespaceHandler.ensure_final_newline("hello\n\n\n")
        assert result == "hello\n"


# ---------------------------------------------------------------------------
# clean_whitespace
# ---------------------------------------------------------------------------

class TestCleanWhitespace:
    """Tests for WhitespaceHandler.clean_whitespace."""

    def test_comprehensive_cleanup(self):
        code = "def foo():  \n    pass  \n\n\n\n\n    return 1  "
        result = WhitespaceHandler.clean_whitespace(code, language="python")
        # trailing whitespace removed
        assert "  \n" not in result
        # ends with newline
        assert result.endswith("\n")
        # excessive blank lines collapsed (max 2 consecutive)
        assert "\n\n\n\n" not in result

    def test_empty_code(self):
        # empty string → normalize returns "" → strip trailing returns ""
        # → ensure_final_newline returns "\n", then the regex won't match
        result = WhitespaceHandler.clean_whitespace("")
        # detect_indent on "" has no lines → should handle gracefully
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _find_indent_size
# ---------------------------------------------------------------------------

class TestFindIndentSize:
    """Tests for the internal _find_indent_size."""

    def test_empty_list(self):
        assert WhitespaceHandler._find_indent_size([]) == 4

    def test_consistent_four_spaces(self):
        assert WhitespaceHandler._find_indent_size([4, 8, 12]) == 4

    def test_consistent_two_spaces(self):
        assert WhitespaceHandler._find_indent_size([2, 4, 6, 8]) == 2

    def test_single_value(self):
        result = WhitespaceHandler._find_indent_size([4])
        assert isinstance(result, int)
        assert result > 0
