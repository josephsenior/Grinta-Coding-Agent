"""Tests for backend.adapters.io — command-line input/task helpers."""

import argparse
from unittest.mock import mock_open, patch

import pytest

from backend.adapters.io import read_input, read_task, read_task_from_file


class TestReadInput:
    """Tests for read_input function."""

    @patch("builtins.input", return_value="Hello, world!")
    def test_single_line_input(self, mock_input):
        """Test single-line input mode."""
        result = read_input(cli_multiline_input=False)
        assert result == "Hello, world!"
        mock_input.assert_called_once_with(">> ")

    @patch("builtins.input", return_value="  trailing spaces  ")
    def test_single_line_strips_trailing(self, mock_input):
        """Test single-line input strips trailing whitespace."""
        result = read_input(cli_multiline_input=False)
        assert result == "  trailing spaces"

    @patch("builtins.input", side_effect=["line1", "line2", "/exit"])
    def test_multiline_input(self, mock_input):
        """Test multiline input mode."""
        result = read_input(cli_multiline_input=True)
        assert result == "line1\nline2"
        assert mock_input.call_count == 3

    @patch("builtins.input", side_effect=["/exit"])
    def test_multiline_immediate_exit(self, mock_input):
        """Test multiline with immediate /exit."""
        result = read_input(cli_multiline_input=True)
        assert result == ""

    @patch("builtins.input", side_effect=["first", "second", "third", "/exit"])
    def test_multiline_multiple_lines(self, mock_input):
        """Test multiline with multiple lines."""
        result = read_input(cli_multiline_input=True)
        assert result == "first\nsecond\nthird"

    @patch("builtins.input", return_value="")
    def test_empty_input(self, mock_input):
        """Test empty input."""
        result = read_input(cli_multiline_input=False)
        assert result == ""

    @patch("builtins.input", side_effect=["  ", "   ", "/exit"])
    def test_multiline_whitespace_lines(self, mock_input):
        """Test multiline with whitespace-only lines."""
        result = read_input(cli_multiline_input=True)
        # Each line is rstripped, so spaces become empty
        assert result == "\n"


class TestReadTaskFromFile:
    """Tests for read_task_from_file function."""

    @patch("builtins.open", new_callable=mock_open, read_data="Task content here")
    def test_read_simple_file(self, mock_file):
        """Test reading a simple task file."""
        result = read_task_from_file("task.txt")
        assert result == "Task content here"
        mock_file.assert_called_once_with("task.txt", encoding="utf-8")

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="Line 1\nLine 2\nLine 3",
    )
    def test_read_multiline_file(self, mock_file):
        """Test reading multiline task file."""
        result = read_task_from_file("task.txt")
        assert result == "Line 1\nLine 2\nLine 3"

    @patch("builtins.open", new_callable=mock_open, read_data="")
    def test_read_empty_file(self, mock_file):
        """Test reading empty file."""
        result = read_task_from_file("empty.txt")
        assert result == ""

    @patch("builtins.open", new_callable=mock_open, read_data="Unicode: 你好 🚀")
    def test_read_unicode_file(self, mock_file):
        """Test reading file with unicode."""
        result = read_task_from_file("unicode.txt")
        assert result == "Unicode: 你好 🚀"

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_file_not_found(self, mock_file):
        """Test FileNotFoundError when file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            read_task_from_file("nonexistent.txt")

    @patch("builtins.open", side_effect=PermissionError)
    def test_permission_error(self, mock_file):
        """Test PermissionError when can't read file."""
        with pytest.raises(PermissionError):
            read_task_from_file("protected.txt")


class TestReadTask:
    """Tests for read_task function — main CLI task acquisition."""

    def test_read_from_file_arg(self):
        """Test reading task from file argument."""
        args = argparse.Namespace(file="task.txt", task=None)

        with patch(
            "backend.adapters.io.read_task_from_file", return_value="File task"
        ):
            result = read_task(args, cli_multiline_input=False)
            assert result == "File task"

    def test_read_from_task_arg(self):
        """Test reading task from task argument."""
        args = argparse.Namespace(file=None, task="Direct task")
        result = read_task(args, cli_multiline_input=False)
        assert result == "Direct task"

    def test_file_takes_precedence_over_task(self):
        """Test file argument takes precedence over task."""
        args = argparse.Namespace(file="task.txt", task="Direct task")

        with patch(
            "backend.adapters.io.read_task_from_file", return_value="File task"
        ):
            result = read_task(args, cli_multiline_input=False)
            assert result == "File task"

    @patch("sys.stdin.isatty", return_value=False)
    @patch("backend.adapters.io.read_input", return_value="Input task")
    def test_read_from_stdin_when_piped(self, mock_read_input, mock_isatty):
        """Test reading from stdin when not a tty."""
        args = argparse.Namespace(file=None, task=None)
        result = read_task(args, cli_multiline_input=True)
        assert result == "Input task"
        mock_read_input.assert_called_once_with(True)

    @patch("sys.stdin.isatty", return_value=True)
    def test_no_input_returns_empty(self, mock_isatty):
        """Test returns empty string when no input source."""
        args = argparse.Namespace(file=None, task=None)
        result = read_task(args, cli_multiline_input=False)
        assert result == ""

    def test_empty_file_returns_empty(self):
        """Test empty file returns empty task."""
        args = argparse.Namespace(file="empty.txt", task=None)

        with patch("backend.adapters.io.read_task_from_file", return_value=""):
            result = read_task(args, cli_multiline_input=False)
            assert result == ""

    @patch("sys.stdin.isatty", return_value=False)
    @patch("backend.adapters.io.read_input", return_value="Multi\nLine\nTask")
    def test_multiline_stdin(self, mock_read_input, mock_isatty):
        """Test multiline input from stdin."""
        args = argparse.Namespace(file=None, task=None)
        result = read_task(args, cli_multiline_input=True)
        assert result == "Multi\nLine\nTask"

    def test_task_arg_with_newlines(self):
        """Test task argument with embedded newlines."""
        args = argparse.Namespace(file=None, task="Task line 1\nTask line 2")
        result = read_task(args, cli_multiline_input=False)
        assert result == "Task line 1\nTask line 2"

    @patch("sys.stdin.isatty", return_value=False)
    @patch("backend.adapters.io.read_input", return_value="")
    def test_empty_stdin(self, mock_read_input, mock_isatty):
        """Test empty stdin input."""
        args = argparse.Namespace(file=None, task=None)
        result = read_task(args, cli_multiline_input=False)
        assert result == ""
