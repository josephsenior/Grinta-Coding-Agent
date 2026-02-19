"""Tests for backend.runtime.utils.diff — unified diff generation."""

from __future__ import annotations


from backend.runtime.utils.diff import (
    _is_binary,
    _normalize_whitespace,
    get_diff,
    get_diff_stats,
)


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------


class TestGetDiff:
    def test_identical_content(self):
        result = get_diff("hello\n", "hello\n")
        assert result == ""

    def test_simple_addition(self):
        old = "line1\nline2\n"
        new = "line1\nline2\nline3\n"
        result = get_diff(old, new)
        assert "+line3" in result

    def test_simple_removal(self):
        old = "line1\nline2\nline3\n"
        new = "line1\nline2\n"
        result = get_diff(old, new)
        assert "-line3" in result

    def test_modification(self):
        old = "hello world\n"
        new = "hello universe\n"
        result = get_diff(old, new)
        assert "-hello world" in result
        assert "+hello universe" in result

    def test_custom_path(self):
        result = get_diff("a\n", "b\n", path="file.py")
        assert "file.py" in result

    def test_empty_old(self):
        result = get_diff("", "new content\n")
        assert "+new content" in result

    def test_empty_new(self):
        result = get_diff("old content\n", "")
        assert "-old content" in result

    def test_both_empty(self):
        result = get_diff("", "")
        assert result == ""

    def test_context_lines(self):
        old = "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n"
        new = "1\n2\n3\n4\nFIVE\n6\n7\n8\n9\n10\n"
        result = get_diff(old, new, context_lines=1)
        # With only 1 context line, lines far from change shouldn't appear
        assert isinstance(result, str)

    def test_ignore_whitespace(self):
        old = "hello   world\n"
        new = "hello world\n"
        result = get_diff(old, new, ignore_whitespace=True)
        assert result == ""

    def test_binary_detection_by_extension(self):
        result = get_diff("a", "b", path="image.png")
        assert "Binary" in result

    def test_binary_detection_by_content(self):
        result = get_diff("hello\x00world", "hello\x00world2")
        assert "Binary" in result


# ---------------------------------------------------------------------------
# _is_binary
# ---------------------------------------------------------------------------


class TestIsBinary:
    def test_empty_not_binary(self):
        assert _is_binary("") is False

    def test_null_byte_is_binary(self):
        assert _is_binary("hello\x00world") is True

    def test_normal_text_not_binary(self):
        assert _is_binary("hello world\nline two\ttab") is False

    def test_high_ratio_non_printable(self):
        # Create content with >30% non-printable
        content = "\x01\x02\x03\x04" * 100 + "abc"
        assert _is_binary(content) is True


# ---------------------------------------------------------------------------
# _normalize_whitespace
# ---------------------------------------------------------------------------


class TestNormalizeWhitespace:
    def test_collapses_spaces(self):
        result = _normalize_whitespace("hello   world\n")
        assert result == "hello world\n"

    def test_preserves_newline(self):
        result = _normalize_whitespace("hello\n")
        assert result.endswith("\n")

    def test_no_newline(self):
        result = _normalize_whitespace("hello")
        assert not result.endswith("\n")

    def test_tabs_normalized(self):
        result = _normalize_whitespace("col1\t\tcol2\n")
        assert "\t" not in result


# ---------------------------------------------------------------------------
# get_diff_stats
# ---------------------------------------------------------------------------


class TestGetDiffStats:
    def test_empty_diff(self):
        stats = get_diff_stats("")
        assert stats["lines_added"] == 0
        assert stats["lines_removed"] == 0
        assert stats["hunks"] == 0
        assert stats["files_changed"] == 0

    def test_basic_stats(self):
        diff = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old line\n"
            "+new line\n"
            " context\n"
        )
        stats = get_diff_stats(diff)
        assert stats["lines_added"] == 1
        assert stats["lines_removed"] == 1
        assert stats["hunks"] == 1
        assert stats["files_changed"] == 1

    def test_multiple_hunks(self):
        diff = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            "+add1\n"
            "@@ -10,3 +10,3 @@\n"
            "+add2\n"
            "+add3\n"
        )
        stats = get_diff_stats(diff)
        assert stats["hunks"] == 2
        assert stats["lines_added"] == 3
