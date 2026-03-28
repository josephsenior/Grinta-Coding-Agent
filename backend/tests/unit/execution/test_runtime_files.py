"""Tests for backend.execution.utils.files module."""

import os
from pathlib import Path

import pytest


class TestResolvePath:
    def test_absolute_within_workspace(self, tmp_path):
        from backend.execution.utils.files import resolve_path

        workspace = str(tmp_path)
        file_path = str(tmp_path / "test.txt")
        result = resolve_path(file_path, workspace, workspace)
        assert result == Path(file_path).resolve()

    def test_relative_within_workspace(self, tmp_path):
        from backend.execution.utils.files import resolve_path

        workspace = str(tmp_path)
        result = resolve_path("test.txt", workspace, workspace)
        assert result == (tmp_path / "test.txt").resolve()

    def test_path_outside_workspace_raises(self, tmp_path):
        from backend.execution.utils.files import resolve_path

        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)
        with pytest.raises(PermissionError, match="File access not permitted"):
            resolve_path("../../etc/passwd", workspace, workspace)

    def test_absolute_outside_workspace_raises(self, tmp_path):
        from backend.execution.utils.files import resolve_path

        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)
        outside = str(tmp_path / "outside" / "file.txt")
        with pytest.raises(PermissionError, match="File access not permitted"):
            resolve_path(outside, workspace, workspace)

    def test_subdirectory_within_workspace(self, tmp_path):
        from backend.execution.utils.files import resolve_path

        workspace = str(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        result = resolve_path("sub/test.txt", workspace, workspace)
        assert result == (sub / "test.txt").resolve()


class TestReadLines:
    def test_read_all(self):
        from backend.execution.utils.files import read_lines

        lines = ["a\n", "b\n", "c\n"]
        assert read_lines(lines) == lines

    def test_read_from_start(self):
        from backend.execution.utils.files import read_lines

        lines = ["a\n", "b\n", "c\n", "d\n"]
        assert read_lines(lines, start=2) == ["c\n", "d\n"]

    def test_read_with_end(self):
        from backend.execution.utils.files import read_lines

        lines = ["a\n", "b\n", "c\n", "d\n"]
        assert read_lines(lines, start=1, end=3) == ["b\n", "c\n"]

    def test_negative_start_clamped(self):
        from backend.execution.utils.files import read_lines

        lines = ["a\n", "b\n"]
        assert read_lines(lines, start=-5) == lines

    def test_end_before_start_returns_empty(self):
        from backend.execution.utils.files import read_lines

        lines = ["a\n", "b\n", "c\n"]
        # end is clamped to max(start, end) = max(2, 1) = 2 → lines[2:2] = []
        assert read_lines(lines, start=2, end=1) == []

    def test_empty_list(self):
        from backend.execution.utils.files import read_lines

        assert read_lines([]) == []


class TestInsertLines:
    def test_insert_at_beginning(self):
        from backend.execution.utils.files import insert_lines

        original = ["a\n", "b\n", "c\n"]
        result = insert_lines(["x", "y"], original, start=0, end=0)
        # start==0 means new_lines starts with [""]
        assert "x\n" in result
        assert "y\n" in result

    def test_insert_at_end(self):
        from backend.execution.utils.files import insert_lines

        original = ["a\n", "b\n"]
        result = insert_lines(["z"], original, start=2, end=-1)
        assert result[0:2] == ["a\n", "b\n"]
        assert "z\n" in result

    def test_replace_middle(self):
        from backend.execution.utils.files import insert_lines

        original = ["a\n", "b\n", "c\n", "d\n"]
        result = insert_lines(["X"], original, start=1, end=3)
        assert result == ["a\n", "X\n", "d\n"]


class TestReadFile:
    async def test_read_existing_file(self, tmp_path):
        from backend.execution.utils.files import read_file

        f = tmp_path / "test.txt"
        f.write_text("hello\nworld\n", encoding="utf-8")
        obs = await read_file(str(f), str(tmp_path), str(tmp_path))
        from backend.ledger.observation import FileReadObservation

        assert isinstance(obs, FileReadObservation)
        assert "hello" in obs.content

    async def test_read_nonexistent_file(self, tmp_path):
        from backend.execution.utils.files import read_file

        obs = await read_file("nofile.txt", str(tmp_path), str(tmp_path))
        from backend.ledger.observation import ErrorObservation

        assert isinstance(obs, ErrorObservation)

    async def test_read_outside_workspace(self, tmp_path):
        from backend.execution.utils.files import read_file

        workspace = tmp_path / "ws"
        workspace.mkdir()
        obs = await read_file("../../etc/passwd", str(workspace), str(workspace))
        from backend.ledger.observation import ErrorObservation

        assert isinstance(obs, ErrorObservation)
        assert "not allowed" in str(obs).lower() or "allowed" in str(obs).lower()

    async def test_read_with_line_range(self, tmp_path):
        from backend.execution.utils.files import read_file

        f = tmp_path / "lines.txt"
        f.write_text("line0\nline1\nline2\nline3\n", encoding="utf-8")
        obs = await read_file(str(f), str(tmp_path), str(tmp_path), start=1, end=3)
        from backend.ledger.observation import FileReadObservation

        assert isinstance(obs, FileReadObservation)
        assert "line1" in obs.content
        assert "line2" in obs.content
        assert "line0" not in obs.content
        assert "line3" not in obs.content

    async def test_read_directory_returns_error(self, tmp_path):
        from backend.execution.utils.files import read_file

        obs = await read_file(str(tmp_path), str(tmp_path), str(tmp_path))
        from backend.ledger.observation import ErrorObservation

        # On Windows, open(directory, encoding="utf-8") raises PermissionError which is caught
        # and turned into an ErrorObservation; on Linux it's IsADirectoryError.
        assert isinstance(obs, ErrorObservation)


class TestWriteFile:
    async def test_write_new_file(self, tmp_path):
        from backend.execution.utils.files import write_file

        obs = await write_file("new.txt", str(tmp_path), str(tmp_path), "hello world")
        from backend.ledger.observation import FileWriteObservation

        assert isinstance(obs, FileWriteObservation)
        assert (tmp_path / "new.txt").exists()

    async def test_write_creates_directories(self, tmp_path):
        from backend.execution.utils.files import write_file

        obs = await write_file(
            "sub/dir/file.txt", str(tmp_path), str(tmp_path), "content"
        )
        from backend.ledger.observation import FileWriteObservation

        assert isinstance(obs, FileWriteObservation)
        assert (tmp_path / "sub" / "dir" / "file.txt").exists()

    async def test_write_outside_workspace(self, tmp_path):
        from backend.execution.utils.files import write_file

        workspace = tmp_path / "ws"
        workspace.mkdir()
        obs = await write_file("../../bad.txt", str(workspace), str(workspace), "bad")
        from backend.ledger.observation import ErrorObservation

        assert isinstance(obs, ErrorObservation)
