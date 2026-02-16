"""Tests for backend.runtime.utils.git_common — low-level git helpers."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from backend.runtime.utils.git_common import run_git_cmd


class TestRunGitCmd:
    def test_successful_command(self):
        with patch("backend.runtime.utils.git_common.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"main\n",
                stderr=b"",
            )
            result = run_git_cmd("git --no-pager branch", "/repo")
            assert result == "main"

    def test_failed_command_raises(self):
        with patch("backend.runtime.utils.git_common.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128,
                stdout=b"",
                stderr=b"fatal: not a git repository",
            )
            with pytest.raises(RuntimeError, match="error_running_cmd"):
                run_git_cmd("git status", "/repo")

    def test_stderr_preferred_over_stdout(self):
        with patch("backend.runtime.utils.git_common.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"stdout output",
                stderr=b"stderr output",
            )
            result = run_git_cmd("git log", "/repo")
            assert result == "stderr output"

    def test_strips_output(self):
        with patch("backend.runtime.utils.git_common.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"  trimmed  \n",
                stderr=b"",
            )
            result = run_git_cmd("git rev-parse HEAD", "/repo")
            assert result == "trimmed"
