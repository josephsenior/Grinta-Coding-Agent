"""Tests for backend.server.file_config — file upload configuration helpers."""

from __future__ import annotations


from backend.server.file_config import (
    get_unique_filename,
    sanitize_filename,
)


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_normal_filename(self):
        assert sanitize_filename("hello.txt") == "hello.txt"

    def test_strips_directory(self):
        result = sanitize_filename("/some/path/hello.txt")
        assert result == "hello.txt"

    def test_strips_windows_directory(self):
        result = sanitize_filename("C:\\Users\\test\\hello.txt")
        assert result == "hello.txt"

    def test_removes_special_chars(self):
        result = sanitize_filename("file name!@#$.txt")
        assert "!" not in result
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result

    def test_preserves_dots_dashes_underscores(self):
        result = sanitize_filename("my-file_v2.0.txt")
        assert result == "my-file_v2.0.txt"

    def test_truncation_preserves_extension(self):
        # A very long filename should be truncated but keep the extension
        long_name = "a" * 500 + ".py"
        result = sanitize_filename(long_name)
        assert result.endswith(".py")
        assert len(result) <= 256  # MAX_FILENAME_LENGTH or similar

    def test_traversal_path_stripped(self):
        result = sanitize_filename("../../etc/passwd")
        # os.path.basename gives "passwd"
        assert ".." not in result
        assert result == "passwd"


# ---------------------------------------------------------------------------
# get_unique_filename
# ---------------------------------------------------------------------------


class TestGetUniqueFilename:
    def test_no_conflict(self, tmp_path):
        result = get_unique_filename("new_file.txt", str(tmp_path))
        assert result == "new_file.txt"

    def test_single_conflict(self, tmp_path):
        (tmp_path / "report.txt").touch()
        result = get_unique_filename("report.txt", str(tmp_path))
        assert result == "report copy.txt"

    def test_multiple_conflicts(self, tmp_path):
        (tmp_path / "data.txt").touch()
        (tmp_path / "data copy.txt").touch()
        result = get_unique_filename("data.txt", str(tmp_path))
        assert result == "data copy(1).txt"

    def test_many_conflicts(self, tmp_path):
        (tmp_path / "x.txt").touch()
        (tmp_path / "x copy.txt").touch()
        (tmp_path / "x copy(1).txt").touch()
        (tmp_path / "x copy(2).txt").touch()
        result = get_unique_filename("x.txt", str(tmp_path))
        assert result == "x copy(3).txt"

    def test_no_extension(self, tmp_path):
        (tmp_path / "README").touch()
        result = get_unique_filename("README", str(tmp_path))
        assert "copy" in result
