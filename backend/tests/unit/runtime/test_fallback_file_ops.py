"""Tests for backend.runtime.utils.fallbacks.file_ops module.

Targets 0% coverage (87 statements).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from backend.runtime.utils.fallbacks.file_ops import PythonFileOps


# -----------------------------------------------------------
# normalize_path
# -----------------------------------------------------------


class TestNormalizePath:
    def test_string_input(self, tmp_path: Path):
        result = PythonFileOps.normalize_path(str(tmp_path))
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_path_input(self, tmp_path: Path):
        result = PythonFileOps.normalize_path(tmp_path)
        assert result.is_absolute()

    def test_relative_path_resolved(self):
        result = PythonFileOps.normalize_path(".")
        assert result.is_absolute()


# -----------------------------------------------------------
# is_hidden
# -----------------------------------------------------------


class TestIsHidden:
    @pytest.mark.skipif(sys.platform == "win32", reason="dotfile not hidden on Windows")
    def test_dotfile_is_hidden_unix(self, tmp_path: Path):
        dotfile = tmp_path / ".hidden"
        dotfile.write_text("x")
        assert PythonFileOps.is_hidden(dotfile) is True

    def test_normal_file_not_hidden(self, tmp_path: Path):
        f = tmp_path / "visible.txt"
        f.write_text("x")
        assert PythonFileOps.is_hidden(f) is False

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_dotfile_fallback_on_windows(self, tmp_path: Path):
        # On Windows, is_hidden checks FILE_ATTRIBUTE_HIDDEN, not dot prefix
        # A dotfile that doesn't have the hidden attribute returns based on
        # the fallback (dot prefix check) or the attribute check
        dotfile = tmp_path / ".hidden"
        dotfile.write_text("x")
        # Just ensure it returns a bool without error
        assert isinstance(PythonFileOps.is_hidden(dotfile), bool)


# -----------------------------------------------------------
# list_directory
# -----------------------------------------------------------


class TestListDirectory:
    def test_non_directory_returns_empty(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        assert PythonFileOps.list_directory(f) == []

    def test_lists_files(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = PythonFileOps.list_directory(tmp_path)
        names = {p.name for p in result}
        assert "a.txt" in names
        assert "b.txt" in names

    @pytest.mark.skipif(sys.platform == "win32", reason="dotfile not hidden on Windows")
    def test_excludes_hidden_by_default_unix(self, tmp_path: Path):
        (tmp_path / ".hidden").write_text("x")
        (tmp_path / "visible.txt").write_text("y")
        result = PythonFileOps.list_directory(tmp_path, include_hidden=False)
        names = {p.name for p in result}
        assert "visible.txt" in names
        assert ".hidden" not in names

    def test_includes_hidden_when_requested(self, tmp_path: Path):
        (tmp_path / ".hidden").write_text("x")
        result = PythonFileOps.list_directory(tmp_path, include_hidden=True)
        names = {p.name for p in result}
        assert ".hidden" in names

    def test_recursive_listing(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")
        (tmp_path / "top.txt").write_text("top")
        result = PythonFileOps.list_directory(tmp_path, recursive=True)
        names = {p.name for p in result}
        assert "top.txt" in names
        assert "deep.txt" in names

    @pytest.mark.skipif(sys.platform == "win32", reason="dotfile not hidden on Windows")
    def test_recursive_excludes_hidden_dirs_unix(self, tmp_path: Path):
        hidden_dir = tmp_path / ".hdir"
        hidden_dir.mkdir()
        (hidden_dir / "secret.txt").write_text("s")
        (tmp_path / "ok.txt").write_text("ok")
        result = PythonFileOps.list_directory(
            tmp_path, recursive=True, include_hidden=False
        )
        names = {p.name for p in result}
        assert "ok.txt" in names
        assert "secret.txt" not in names

    def test_sorted_results(self, tmp_path: Path):
        (tmp_path / "c.txt").write_text("c")
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = PythonFileOps.list_directory(tmp_path)
        names = [p.name for p in result]
        assert names == sorted(names)


# -----------------------------------------------------------
# safe_read_text
# -----------------------------------------------------------


class TestSafeReadText:
    def test_reads_content(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = PythonFileOps.safe_read_text(f)
        assert result == "hello world"

    def test_nonexistent_returns_none(self):
        result = PythonFileOps.safe_read_text("/nonexistent_xyz/file.txt")
        assert result is None

    def test_string_path(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("data")
        result = PythonFileOps.safe_read_text(str(f))
        assert result == "data"


# -----------------------------------------------------------
# safe_write_text
# -----------------------------------------------------------


class TestSafeWriteText:
    def test_writes_content(self, tmp_path: Path):
        f = tmp_path / "out.txt"
        assert PythonFileOps.safe_write_text(f, "hello") is True
        assert f.read_text() == "hello"

    def test_creates_parent_dirs(self, tmp_path: Path):
        f = tmp_path / "a" / "b" / "c.txt"
        assert PythonFileOps.safe_write_text(f, "nested") is True
        assert f.read_text() == "nested"

    def test_no_create_dirs_fails(self, tmp_path: Path):
        f = tmp_path / "x" / "y" / "z.txt"
        result = PythonFileOps.safe_write_text(f, "data", create_dirs=False)
        assert result is False


# -----------------------------------------------------------
# get_file_size
# -----------------------------------------------------------


class TestGetFileSize:
    def test_returns_size(self, tmp_path: Path):
        f = tmp_path / "sized.txt"
        f.write_text("12345")
        size = PythonFileOps.get_file_size(f)
        assert size == 5

    def test_nonexistent_returns_none(self):
        assert PythonFileOps.get_file_size("/nonexistent_xyz/file") is None


# -----------------------------------------------------------
# is_executable
# -----------------------------------------------------------


class TestIsExecutable:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_exe_on_windows(self, tmp_path: Path):
        f = tmp_path / "app.exe"
        f.write_text("fake exe")
        assert PythonFileOps.is_executable(f) is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_bat_on_windows(self, tmp_path: Path):
        f = tmp_path / "run.bat"
        f.write_text("echo hi")
        assert PythonFileOps.is_executable(f) is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_txt_not_executable_on_windows(self, tmp_path: Path):
        f = tmp_path / "readme.txt"
        f.write_text("hi")
        assert PythonFileOps.is_executable(f) is False

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-only")
    def test_executable_bit_on_unix(self, tmp_path: Path):
        f = tmp_path / "script.sh"
        f.write_text("#!/bin/sh\necho hi")
        os.chmod(f, 0o755)
        assert PythonFileOps.is_executable(f) is True
