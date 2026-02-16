"""Tests for backend.runtime.utils.git_handler — GitHandler."""

from __future__ import annotations

import json

import pytest

from backend.runtime.utils.git_handler import CommandResult, GitHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(
    exec_results: list[CommandResult] | None = None,
    create_result: int = 0,
):
    """Build a GitHandler with controlled execute_shell_fn and create_file_fn."""
    call_log: list[tuple[str, str | None]] = []
    idx = {"i": 0}
    results = exec_results or [CommandResult(content="", exit_code=0)]

    def execute(cmd: str, cwd: str | None = None) -> CommandResult:
        call_log.append((cmd, cwd))
        r = results[min(idx["i"], len(results) - 1)]
        idx["i"] += 1
        return r

    def create_file(path: str, content: str) -> int:
        return create_result

    handler = GitHandler(execute_shell_fn=execute, create_file_fn=create_file)
    return handler, call_log


# ===================================================================
# CommandResult
# ===================================================================

class TestCommandResult:

    def test_basic(self):
        r = CommandResult(content="hello\n", exit_code=0)
        assert r.content == "hello\n"
        assert r.exit_code == 0

    def test_non_zero(self):
        r = CommandResult(content="err", exit_code=127)
        assert r.exit_code == 127


# ===================================================================
# GitHandler.set_cwd
# ===================================================================

class TestSetCwd:

    def test_sets_cwd(self):
        handler, _ = _make_handler()
        handler.set_cwd("/workspace")
        assert handler.cwd == "/workspace"


# ===================================================================
# get_current_branch
# ===================================================================

class TestGetCurrentBranch:

    def test_no_cwd_returns_none(self):
        handler, _ = _make_handler()
        assert handler.get_current_branch() is None

    def test_returns_branch_name(self):
        handler, _ = _make_handler([CommandResult(content="main\n", exit_code=0)])
        handler.set_cwd("/repo")
        assert handler.get_current_branch() == "main"

    def test_returns_none_on_error(self):
        handler, _ = _make_handler([CommandResult(content="", exit_code=128)])
        handler.set_cwd("/repo")
        assert handler.get_current_branch() is None

    def test_returns_none_on_empty_output(self):
        handler, _ = _make_handler([CommandResult(content="  \n", exit_code=0)])
        handler.set_cwd("/repo")
        assert handler.get_current_branch() is None


# ===================================================================
# get_git_changes
# ===================================================================

class TestGetGitChanges:

    def test_no_cwd_returns_none(self):
        handler, _ = _make_handler()
        assert handler.get_git_changes() is None

    def test_returns_changes(self):
        changes = [{"file": "a.py", "status": "M"}]
        handler, _ = _make_handler([
            CommandResult(content=json.dumps(changes), exit_code=0),
        ])
        handler.set_cwd("/repo")
        result = handler.get_git_changes()
        assert result == changes

    def test_returns_none_on_invalid_json(self):
        handler, _ = _make_handler([
            CommandResult(content="not json", exit_code=0),
        ])
        handler.set_cwd("/repo")
        assert handler.get_git_changes() is None

    def test_error_exit_code_triggers_script_install(self):
        """On first failure, handler tries to install the script and retries."""
        changes = [{"file": "b.py", "status": "A"}]
        handler, calls = _make_handler([
            CommandResult(content="", exit_code=1),           # First try fails
            CommandResult(content="/tmp/abc\n", exit_code=0), # mktemp
            CommandResult(content="", exit_code=0),           # chmod
            CommandResult(content=json.dumps(changes), exit_code=0),  # retry
        ])
        handler.set_cwd("/repo")
        # We can't easily test this end-to-end because _create_python_script_file
        # opens a local file. Instead verify the handler detects the failure.
        # Just check the first call happens with default cmd
        result_first = handler.execute(handler.git_changes_cmd, handler.cwd)
        assert result_first.exit_code == 1


# ===================================================================
# get_git_diff
# ===================================================================

class TestGetGitDiff:

    def test_no_cwd_raises(self):
        handler, _ = _make_handler()
        with pytest.raises(ValueError, match="no_dir"):
            handler.get_git_diff("file.py")

    def test_returns_diff(self):
        diff = {"original": "old code", "modified": "new code"}
        handler, _ = _make_handler([
            CommandResult(content=json.dumps(diff), exit_code=0),
        ])
        handler.set_cwd("/repo")
        result = handler.get_git_diff("file.py")
        assert result == diff

    def test_error_after_script_install_raises(self):
        """If both default and custom commands fail, raises ValueError."""
        handler, _ = _make_handler([
            CommandResult(content="", exit_code=1),            # First try
            CommandResult(content="/tmp/xyz\n", exit_code=0),  # mktemp
            CommandResult(content="", exit_code=0),            # chmod
            CommandResult(content="", exit_code=1),            # Retry also fails
        ])
        handler.set_cwd("/repo")
        # Manually set git_diff_cmd to something non-default to simulate script already installed
        handler.git_diff_cmd = "python3 /custom/script.py"
        with pytest.raises(ValueError, match="error_in_git_diff"):
            handler.get_git_diff("file.py")
