"""Tests for backend.runtime.git_setup module.

Targets 16.7% coverage (126 statements) by testing:
- GitSetupMixin helper methods for git hooks and config
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.events.action import CmdRunAction, FileReadAction, FileWriteAction
from backend.events.observation import CmdOutputObservation, ErrorObservation
from backend.runtime.git_setup import GitSetupMixin


# -----------------------------------------------------------
# Fake Host
# -----------------------------------------------------------


class _FakeGitRuntime(GitSetupMixin):
    """Concrete host for GitSetupMixin testing."""

    def __init__(self) -> None:
        self.sid = "test-sid"
        self.config = MagicMock()
        self.config.init_git_in_empty_workspace = False
        self.config.vcs_user_name = "Test User"
        self.config.vcs_user_email = "test@example.com"
        self.workspace_root = Path("/test/workspace")
        self.event_stream = None
        self.status_callback = None
        self.provider_handler = MagicMock()
        self._read_results: dict[str, Any] = {}
        self._write_results: dict[str, Any] = {}
        self._run_results: list[Any] = []

    def log(self, level: str, message: str) -> None:
        pass

    def read(self, action: FileReadAction) -> Any:
        return self._read_results.get(action.path, ErrorObservation("Not found"))

    def write(self, action: FileWriteAction) -> Any:
        return self._write_results.get(action.path, MagicMock())

    def run(self, action: CmdRunAction) -> Any:
        if self._run_results:
            return self._run_results.pop(0)
        return CmdOutputObservation(content="", command=action.command, exit_code=0)

    def run_action(self, action: Any) -> Any:
        if isinstance(action, CmdRunAction):
            return self.run(action)
        if isinstance(action, FileReadAction):
            return self.read(action)
        if isinstance(action, FileWriteAction):
            return self.write(action)
        return MagicMock()

    def set_runtime_status(
        self, status: Any, msg: str = "", level: str = "info"
    ) -> None:
        pass


# -----------------------------------------------------------
# _setup_git_hooks_directory
# -----------------------------------------------------------


class TestSetupGitHooksDirectory:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content="", command="mkdir -p .git/hooks", exit_code=0)
        ]
        assert runtime._setup_git_hooks_directory() is True

    def test_failure_exit_code(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(
                content="Error", command="mkdir -p .git/hooks", exit_code=1
            )
        ]
        assert runtime._setup_git_hooks_directory() is False

    def test_non_cmd_output(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [ErrorObservation("Error")]
        assert runtime._setup_git_hooks_directory() is False


# -----------------------------------------------------------
# _make_script_executable
# -----------------------------------------------------------


class TestMakeScriptExecutable:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content="", command="chmod +x script.sh", exit_code=0)
        ]
        assert runtime._make_script_executable("script.sh") is True

    def test_failure_exit_code(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(
                content="Permission denied", command="chmod +x script.sh", exit_code=1
            )
        ]
        assert runtime._make_script_executable("script.sh") is False

    def test_non_cmd_output(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [ErrorObservation("Error")]
        assert runtime._make_script_executable("script.sh") is False


# -----------------------------------------------------------
# _preserve_existing_hook
# -----------------------------------------------------------


class TestPreserveExistingHook:
    def test_success_mv_command(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content="", command="mv", exit_code=0),  # mv
            CmdOutputObservation(content="", command="chmod", exit_code=0),  # chmod
        ]
        assert runtime._preserve_existing_hook(".git/hooks/pre-commit") is True

    def test_mv_fails_falls_back_to_shutil(self):
        runtime = _FakeGitRuntime()
        # Return ErrorObservation (not CmdOutputObservation) to trigger shutil fallback
        runtime._run_results = [
            ErrorObservation("mv failed"),  # mv fails with error (not CmdOutput)
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod after shutil.move
        ]
        with patch("backend.runtime.git_setup.shutil.move"):
            assert runtime._preserve_existing_hook(".git/hooks/pre-commit") is True

    def test_shutil_raises_oserror(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            ErrorObservation(
                "mv command error"
            ),  # Not a CmdOutputObservation -> triggers shutil
        ]
        with patch(
            "backend.runtime.git_setup.shutil.move", side_effect=OSError("fail")
        ):
            assert runtime._preserve_existing_hook(".git/hooks/pre-commit") is False

    def test_chmod_fails_after_move(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content="", command="mv", exit_code=0),  # mv
            CmdOutputObservation(
                content="chmod failed", command="chmod", exit_code=1
            ),  # chmod
        ]
        assert runtime._preserve_existing_hook(".git/hooks/pre-commit") is False


# -----------------------------------------------------------
# _install_pre_commit_hook
# -----------------------------------------------------------


class TestInstallPreCommitHook:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._write_results[".git/hooks/pre-commit"] = MagicMock()
        runtime._run_results = [
            CmdOutputObservation(content="", command="chmod", exit_code=0)
        ]  # chmod
        result = runtime._install_pre_commit_hook(
            ".Forge/pre-commit.sh", ".git/hooks/pre-commit"
        )
        assert result is True

    def test_write_fails(self):
        runtime = _FakeGitRuntime()
        runtime._write_results[".git/hooks/pre-commit"] = ErrorObservation(
            "Write error"
        )
        result = runtime._install_pre_commit_hook(
            ".Forge/pre-commit.sh", ".git/hooks/pre-commit"
        )
        assert result is False

    def test_chmod_fails(self):
        runtime = _FakeGitRuntime()
        runtime._write_results[".git/hooks/pre-commit"] = MagicMock()
        runtime._run_results = [
            CmdOutputObservation(content="chmod failed", command="chmod", exit_code=1)
        ]
        result = runtime._install_pre_commit_hook(
            ".Forge/pre-commit.sh", ".git/hooks/pre-commit"
        )
        assert result is False


# -----------------------------------------------------------
# maybe_run_setup_script
# -----------------------------------------------------------


class TestMaybeRunSetupScript:
    def test_no_setup_script(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/setup.sh"] = ErrorObservation("Not found")
        runtime.maybe_run_setup_script()
        # Should return early without running action

    def test_setup_script_exists(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/setup.sh"] = MagicMock(
            content="#!/bin/bash\necho 'setup'"
        )
        runtime._run_results = [
            CmdOutputObservation(content="", command="chmod", exit_code=0)
        ]
        runtime.maybe_run_setup_script()
        # Should run action

    def test_setup_script_with_status_callback(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/setup.sh"] = MagicMock(content="#!/bin/bash")
        runtime._run_results = [
            CmdOutputObservation(content="", command="chmod", exit_code=0)
        ]
        runtime.status_callback = MagicMock()
        runtime.maybe_run_setup_script()
        # Status callback should be called


# -----------------------------------------------------------
# maybe_setup_git_hooks
# -----------------------------------------------------------


class TestMaybeSetupGitHooks:
    def test_no_pre_commit_script(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/pre-commit.sh"] = ErrorObservation("Not found")
        runtime.maybe_setup_git_hooks()
        # Should return early

    def test_hooks_directory_creation_fails(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/pre-commit.sh"] = MagicMock(content="#!/bin/bash")
        runtime._run_results = [
            CmdOutputObservation(content="mkdir failed", command="mkdir", exit_code=1)
        ]
        runtime.maybe_setup_git_hooks()
        # Should return early after mkdir fails

    def test_chmod_pre_commit_script_fails(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/pre-commit.sh"] = MagicMock(content="#!/bin/bash")
        runtime._run_results = [
            CmdOutputObservation(content="", command="mkdir", exit_code=0),  # mkdir
            CmdOutputObservation(
                content="chmod failed", command="chmod", exit_code=1
            ),  # chmod
        ]
        runtime.maybe_setup_git_hooks()
        # Should return early after chmod fails

    def test_preserve_existing_hook(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/pre-commit.sh"] = MagicMock(content="#!/bin/bash")
        runtime._read_results[".git/hooks/pre-commit"] = MagicMock(
            content="#!/bin/bash\nexisting hook"
        )
        runtime._run_results = [
            CmdOutputObservation(content="", command="mkdir", exit_code=0),  # mkdir
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod pre-commit.sh
            CmdOutputObservation(
                content="", command="mv", exit_code=0
            ),  # mv existing hook
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod .local
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod new hook
        ]
        runtime._write_results[".git/hooks/pre-commit"] = MagicMock()
        runtime.maybe_setup_git_hooks()
        # Should preserve existing hook

    def test_skip_if_forge_installed(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/pre-commit.sh"] = MagicMock(content="#!/bin/bash")
        runtime._read_results[".git/hooks/pre-commit"] = MagicMock(
            content="#!/bin/bash\n# This hook was installed by Forge\n"
        )
        runtime._run_results = [
            CmdOutputObservation(content="", command="mkdir", exit_code=0),  # mkdir
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod pre-commit.sh
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod new hook
        ]
        runtime._write_results[".git/hooks/pre-commit"] = MagicMock()
        runtime.maybe_setup_git_hooks()
        # Should not preserve if already Forge hook

    def test_preserve_fails(self):
        runtime = _FakeGitRuntime()
        runtime._read_results[".Forge/pre-commit.sh"] = MagicMock(content="#!/bin/bash")
        runtime._read_results[".git/hooks/pre-commit"] = MagicMock(content="existing")
        runtime._run_results = [
            CmdOutputObservation(content="", command="mkdir", exit_code=0),  # mkdir
            CmdOutputObservation(
                content="", command="chmod", exit_code=0
            ),  # chmod pre-commit.sh
            CmdOutputObservation(
                content="mv failed", command="mv", exit_code=1
            ),  # mv fails
        ]
        with patch(
            "backend.runtime.git_setup.shutil.move", side_effect=OSError("fail")
        ):
            runtime.maybe_setup_git_hooks()
        # Should return early if preserve fails


# -----------------------------------------------------------
# _setup_git_config
# -----------------------------------------------------------


class TestSetupGitConfig:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content="", command="git config", exit_code=0)
        ]
        runtime._setup_git_config()
        # Should succeed without error

    def test_command_fails(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(
                content="git config failed", command="git config", exit_code=1
            )
        ]
        runtime._setup_git_config()
        # Should log warning but not raise

    def test_exception_raised(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [ErrorObservation("Error")]

        def raise_error(_action):
            raise RuntimeError("git config error")

        runtime.run = raise_error
        runtime._setup_git_config()
        # Should log warning but not raise


# -----------------------------------------------------------
# clone_or_init_repo
# -----------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_or_init_no_repo_no_init():
    runtime = _FakeGitRuntime()
    runtime.config.init_git_in_empty_workspace = False
    result = await runtime.clone_or_init_repo(None, None, None)
    assert result == ""


@pytest.mark.asyncio
async def test_clone_or_init_no_repo_with_init():
    runtime = _FakeGitRuntime()
    runtime.config.init_git_in_empty_workspace = True
    with patch(
        "backend.runtime.git_setup.call_sync_from_async", new_callable=AsyncMock
    ):
        result = await runtime.clone_or_init_repo(None, None, None)
    assert result == ""


@pytest.mark.asyncio
async def test_clone_or_init_no_git_url():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(return_value=None)
    with pytest.raises(
        ValueError, match="Missing either Git token or valid repository"
    ):
        await runtime.clone_or_init_repo(None, "owner/repo", None)


@pytest.mark.asyncio
async def test_clone_or_init_with_branch():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(
        return_value="https://git.example.com/owner/repo.git"
    )
    with patch(
        "backend.runtime.git_setup.call_sync_from_async", new_callable=AsyncMock
    ):
        result = await runtime.clone_or_init_repo(None, "owner/repo", "main")
    assert result == "repo"


@pytest.mark.asyncio
async def test_clone_or_init_no_branch():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(
        return_value="https://git.example.com/owner/MyRepo.git"
    )
    with patch(
        "backend.runtime.git_setup.call_sync_from_async", new_callable=AsyncMock
    ):
        result = await runtime.clone_or_init_repo(None, "owner/MyRepo", None)
    assert result == "myrepo"


@pytest.mark.asyncio
async def test_clone_or_init_with_status_callback():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(
        return_value="https://git.example.com/owner/repo.git"
    )
    runtime.status_callback = MagicMock()
    with patch(
        "backend.runtime.git_setup.call_sync_from_async", new_callable=AsyncMock
    ):
        result = await runtime.clone_or_init_repo(None, "owner/repo", "main")
    assert result == "repo"
    runtime.status_callback.assert_called()
