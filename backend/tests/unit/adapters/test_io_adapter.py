"""Tests for backend.adapters.io — CLI task reading helpers."""

from __future__ import annotations

import argparse

from backend.adapters.io import read_task, read_task_from_file


class TestReadTaskFromFile:
    def test_reads_content(self, tmp_path):
        f = tmp_path / "task.txt"
        f.write_text("Fix the bug in main.py", encoding="utf-8")
        assert read_task_from_file(str(f)) == "Fix the bug in main.py"

    def test_reads_multiline(self, tmp_path):
        f = tmp_path / "task.txt"
        f.write_text("Line1\nLine2\nLine3", encoding="utf-8")
        result = read_task_from_file(str(f))
        assert "Line1" in result
        assert "Line3" in result

    def test_reads_utf8(self, tmp_path):
        f = tmp_path / "task.txt"
        f.write_text("Fix the à la carte bug", encoding="utf-8")
        assert "à la carte" in read_task_from_file(str(f))


class TestReadTask:
    def _make_args(self, task="", file=None):
        ns = argparse.Namespace()
        ns.task = task
        ns.file = file
        return ns

    def test_from_file(self, tmp_path):
        f = tmp_path / "task.txt"
        f.write_text("File task", encoding="utf-8")
        args = self._make_args(file=str(f))
        assert read_task(args, cli_multiline_input=False) == "File task"

    def test_from_args(self):
        args = self._make_args(task="CLI task")
        assert read_task(args, cli_multiline_input=False) == "CLI task"

    def test_file_takes_priority(self, tmp_path):
        f = tmp_path / "task.txt"
        f.write_text("From file", encoding="utf-8")
        args = self._make_args(task="From args", file=str(f))
        assert read_task(args, cli_multiline_input=False) == "From file"

    def test_empty_when_no_input(self, monkeypatch):
        args = self._make_args()
        # Mock stdin input to avoid pytest capture error
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = read_task(args, cli_multiline_input=False)
        assert result == ""
