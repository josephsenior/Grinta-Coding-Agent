"""Tests for backend.execution.git_setup module.

Targets 16.7% coverage (126 statements) by testing:
- GitSetupMixin helper methods for git hooks and config
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.execution.runtime_mixins.git_setup import (
    GitSetupMixin,
    _script_run_command,
)
from backend.ledger.action import CmdRunAction, FileEditAction, FileReadAction
from backend.ledger.observation import CmdOutputObservation, ErrorObservation

# -----------------------------------------------------------
# Fake Host
# -----------------------------------------------------------


class _FakeGitRuntime(GitSetupMixin):
    """Concrete host for GitSetupMixin testing."""

    def __init__(self) -> None:
        self.sid = 'test-sid'
        self.config = MagicMock()
        self.config.init_git_in_empty_workspace = False
        self.config.vcs_user_name = 'Test User'
        self.config.vcs_user_email = 'test@example.com'
        self.workspace_root = Path('/test/workspace')
        self.event_stream = None
        self.status_callback = None
        self.provider_handler = MagicMock()
        self._read_results: dict[str, Any] = {}
        self._write_results: dict[str, Any] = {}
        self._run_results: list[Any] = []
        self._env_vars: dict[str, str] = {}

    def add_env_vars(self, env_vars: dict[str, str]) -> None:
        self._env_vars.update(env_vars)

    def log(self, level: str, message: str) -> None:
        pass

    def read(self, action: FileReadAction) -> Any:
        return self._read_results.get(action.path, ErrorObservation('Not found'))

    def edit(self, action: FileEditAction) -> Any:
        return self._write_results.get(action.path, MagicMock())

    def run(self, action: CmdRunAction) -> Any:
        if self._run_results:
            return self._run_results.pop(0)
        return CmdOutputObservation(content='', command=action.command, exit_code=0)

    def run_action(self, action: Any) -> Any:
        if isinstance(action, CmdRunAction):
            return self.run(action)
        if isinstance(action, FileReadAction):
            return self.read(action)
        if isinstance(action, FileEditAction):
            return self.edit(action)
        return MagicMock()

    def set_runtime_status(
        self, status: Any, msg: str = '', level: str = 'info'
    ) -> None:
        pass


# -----------------------------------------------------------
# _setup_git_hooks_directory
# -----------------------------------------------------------


class TestSetupGitHooksDirectory:
    def test_success(self, tmp_path):
        runtime = _FakeGitRuntime()
        runtime.workspace_root = tmp_path
        assert runtime._setup_git_hooks_directory() is True
        assert (tmp_path / '.git' / 'hooks').is_dir()

    def test_failure(self):
        runtime = _FakeGitRuntime()
        with patch.object(Path, 'mkdir', side_effect=OSError('permission denied')):
            assert runtime._setup_git_hooks_directory() is False

    def test_non_cmd_output(self):
        runtime = _FakeGitRuntime()
        with patch.object(Path, 'mkdir', side_effect=OSError('permission denied')):
            assert runtime._setup_git_hooks_directory() is False


# -----------------------------------------------------------
# _make_script_executable
# -----------------------------------------------------------


class TestMakeScriptExecutable:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod +x script.sh', exit_code=0)
        ]
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            assert runtime._make_script_executable('script.sh') is True

    def test_skips_chmod_on_windows(self):
        runtime = _FakeGitRuntime()
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = True
            assert runtime._make_script_executable('script.ps1') is True
        assert runtime._run_results == []

    def test_failure_exit_code(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(
                content='Permission denied', command='chmod +x script.sh', exit_code=1
            )
        ]
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            assert runtime._make_script_executable('script.sh') is False

    def test_non_cmd_output(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [ErrorObservation('Error')]
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            assert runtime._make_script_executable('script.sh') is False


# -----------------------------------------------------------
# _preserve_existing_hook
# -----------------------------------------------------------


class TestPreserveExistingHook:
    def test_success_mv_command(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0),
        ]
        with patch('backend.execution.runtime_mixins.git_setup.shutil.move'):
            assert runtime._preserve_existing_hook('.git/hooks/pre-commit') is True

    def test_shutil_raises_oserror(self):
        runtime = _FakeGitRuntime()
        with patch(
            'backend.execution.runtime_mixins.git_setup.shutil.move',
            side_effect=OSError('fail'),
        ):
            assert runtime._preserve_existing_hook('.git/hooks/pre-commit') is False

    def test_chmod_fails_after_move(self):
        runtime = _FakeGitRuntime()
        runtime._run_results = [
            CmdOutputObservation(content='chmod failed', command='chmod', exit_code=1),
        ]
        with (
            patch('backend.execution.runtime_mixins.git_setup.shutil.move'),
            patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps,
        ):
            caps.is_windows = False
            assert runtime._preserve_existing_hook('.git/hooks/pre-commit') is False


# -----------------------------------------------------------
# _install_pre_commit_hook
# -----------------------------------------------------------


class TestInstallPreCommitHook:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._write_results['.git/hooks/pre-commit'] = MagicMock()
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0)
        ]  # chmod
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            result = runtime._install_pre_commit_hook(
                '.grinta/pre-commit.sh', '.git/hooks/pre-commit', kind='bash'
            )
        assert result is True

    def test_write_fails(self):
        runtime = _FakeGitRuntime()
        runtime._write_results['.git/hooks/pre-commit'] = ErrorObservation(
            'Write error'
        )
        result = runtime._install_pre_commit_hook(
            '.grinta/pre-commit.sh', '.git/hooks/pre-commit', kind='bash'
        )
        assert result is False

    def test_chmod_fails(self):
        runtime = _FakeGitRuntime()
        runtime._write_results['.git/hooks/pre-commit'] = MagicMock()
        runtime._run_results = [
            CmdOutputObservation(content='chmod failed', command='chmod', exit_code=1)
        ]
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            result = runtime._install_pre_commit_hook(
                '.grinta/pre-commit.sh', '.git/hooks/pre-commit', kind='bash'
            )
        assert result is False


# -----------------------------------------------------------
# maybe_run_setup_script
# -----------------------------------------------------------


class TestMaybeRunSetupScript:
    def test_no_setup_script(self):
        runtime = _FakeGitRuntime()
        runtime._read_results['.grinta/setup.sh'] = ErrorObservation('Not found')
        runtime._read_results['.grinta/setup.ps1'] = ErrorObservation('Not found')
        runtime.maybe_run_setup_script()
        # Should return early without running action

    def test_setup_script_exists(self):
        runtime = _FakeGitRuntime()
        runtime._read_results['.grinta/setup.sh'] = MagicMock(
            content="#!/bin/bash\necho 'setup'"
        )
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0)
        ]
        runtime.maybe_run_setup_script()
        # Should run action

    def test_setup_ps1_on_windows(self):
        runtime = _FakeGitRuntime()
        runtime._read_results['.grinta/setup.ps1'] = MagicMock(
            content="Write-Host 'setup'"
        )
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = True
            runtime.maybe_run_setup_script()
        assert runtime._run_results == []

    def test_setup_script_with_status_callback(self):
        runtime = _FakeGitRuntime()
        runtime._read_results['.grinta/setup.sh'] = MagicMock(content='#!/bin/bash')
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0)
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
        runtime._read_results['.grinta/pre-commit.sh'] = ErrorObservation('Not found')
        runtime._read_results['.grinta/pre-commit.ps1'] = ErrorObservation('Not found')
        runtime.maybe_setup_git_hooks()
        # Should return early

    def test_hooks_directory_creation_fails(self, tmp_path):
        runtime = _FakeGitRuntime()
        runtime.workspace_root = tmp_path
        runtime._read_results['.grinta/pre-commit.sh'] = MagicMock(
            content='#!/bin/bash'
        )
        with patch.object(Path, 'mkdir', side_effect=OSError('mkdir failed')):
            runtime.maybe_setup_git_hooks()
        # Should return early after mkdir fails

    def test_chmod_pre_commit_script_fails(self, tmp_path):
        runtime = _FakeGitRuntime()
        runtime.workspace_root = tmp_path
        runtime._read_results['.grinta/pre-commit.sh'] = MagicMock(
            content='#!/bin/bash'
        )
        runtime._run_results = [
            CmdOutputObservation(content='chmod failed', command='chmod', exit_code=1),
        ]
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            runtime.maybe_setup_git_hooks()
        # Should return early after chmod fails

    def test_preserve_existing_hook(self, tmp_path):
        runtime = _FakeGitRuntime()
        runtime.workspace_root = tmp_path
        runtime._read_results['.grinta/pre-commit.sh'] = MagicMock(
            content='#!/bin/bash'
        )
        runtime._read_results['.git/hooks/pre-commit'] = MagicMock(
            content='#!/bin/bash\nexisting hook'
        )
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0),
            CmdOutputObservation(content='', command='chmod', exit_code=0),
            CmdOutputObservation(content='', command='chmod', exit_code=0),
        ]
        runtime._write_results['.git/hooks/pre-commit'] = MagicMock()
        with patch('backend.execution.runtime_mixins.git_setup.shutil.move'):
            runtime.maybe_setup_git_hooks()
        # Should preserve existing hook

    def test_skip_if_app_installed(self, tmp_path):
        runtime = _FakeGitRuntime()
        runtime.workspace_root = tmp_path
        runtime._read_results['.grinta/pre-commit.sh'] = MagicMock(
            content='#!/bin/bash'
        )
        runtime._read_results['.git/hooks/pre-commit'] = MagicMock(
            content='#!/bin/bash\n# This hook was installed by APP\n'
        )
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0),
            CmdOutputObservation(content='', command='chmod', exit_code=0),
        ]
        runtime._write_results['.git/hooks/pre-commit'] = MagicMock()
        runtime.maybe_setup_git_hooks()
        # Should not preserve if already APP hook

    def test_preserve_fails(self, tmp_path):
        runtime = _FakeGitRuntime()
        runtime.workspace_root = tmp_path
        runtime._read_results['.grinta/pre-commit.sh'] = MagicMock(
            content='#!/bin/bash'
        )
        runtime._read_results['.git/hooks/pre-commit'] = MagicMock(content='existing')
        runtime._run_results = [
            CmdOutputObservation(content='', command='chmod', exit_code=0),
        ]
        with patch(
            'backend.execution.runtime_mixins.git_setup.shutil.move',
            side_effect=OSError('fail'),
        ):
            runtime.maybe_setup_git_hooks()
        # Should return early if preserve fails


class TestScriptRunCommand:
    def test_powershell_command(self):
        cmd = _script_run_command('.grinta/setup.ps1', 'powershell')
        assert 'powershell' in cmd
        assert '.grinta/setup.ps1' in cmd

    def test_bash_command_on_windows(self):
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = True
            cmd = _script_run_command('.grinta/setup.sh', 'bash')
        assert cmd.startswith('bash ')

    def test_bash_command_on_posix(self):
        with patch('backend.execution.runtime_mixins.git_setup.OS_CAPS') as caps:
            caps.is_windows = False
            cmd = _script_run_command('.grinta/setup.sh', 'bash')
        assert 'chmod +x' in cmd


# -----------------------------------------------------------
# _setup_git_config
# -----------------------------------------------------------


class TestSetupGitConfig:
    def test_success(self):
        runtime = _FakeGitRuntime()
        runtime._setup_git_config()
        assert runtime._env_vars['GIT_AUTHOR_NAME'] == 'Test User'
        assert runtime._env_vars['GIT_COMMITTER_EMAIL'] == 'test@example.com'

    def test_command_fails(self):
        runtime = _FakeGitRuntime()

        def raise_on_add(_env_vars: dict[str, str]) -> None:
            raise RuntimeError('env setup failed')

        runtime.add_env_vars = raise_on_add
        runtime._setup_git_config()
        # Should log warning but not raise

    def test_exception_raised(self):
        runtime = _FakeGitRuntime()

        def raise_on_add(_env_vars: dict[str, str]) -> None:
            raise RuntimeError('git config error')

        runtime.add_env_vars = raise_on_add
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
    assert result == ''


@pytest.mark.asyncio
async def test_clone_or_init_no_repo_with_init():
    runtime = _FakeGitRuntime()
    runtime.config.init_git_in_empty_workspace = True
    with patch(
        'backend.execution.runtime_mixins.git_setup.call_sync_from_async',
        new_callable=AsyncMock,
    ):
        result = await runtime.clone_or_init_repo(None, None, None)
    assert result == ''


@pytest.mark.asyncio
async def test_clone_or_init_no_git_url():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(return_value=None)
    with pytest.raises(
        ValueError, match='Missing either Git token or valid repository'
    ):
        await runtime.clone_or_init_repo(None, 'owner/repo', None)


@pytest.mark.asyncio
async def test_clone_or_init_with_branch():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(
        return_value='https://git.example.com/owner/repo.git'
    )
    with patch(
        'backend.execution.runtime_mixins.git_setup.call_sync_from_async',
        new_callable=AsyncMock,
    ):
        result = await runtime.clone_or_init_repo(None, 'owner/repo', 'main')
    assert result == 'repo'


@pytest.mark.asyncio
async def test_clone_or_init_no_branch():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(
        return_value='https://git.example.com/owner/MyRepo.git'
    )
    with patch(
        'backend.execution.runtime_mixins.git_setup.call_sync_from_async',
        new_callable=AsyncMock,
    ) as mock_call:
        result = await runtime.clone_or_init_repo(None, 'owner/MyRepo', None)
    assert result == 'myrepo'
    checkout_action = mock_call.await_args_list[1].args[1]
    assert 'git checkout -b app-workspace-' in checkout_action.command


@pytest.mark.asyncio
async def test_clone_or_init_with_status_callback():
    runtime = _FakeGitRuntime()
    runtime.provider_handler.get_authenticated_git_url = AsyncMock(
        return_value='https://git.example.com/owner/repo.git'
    )
    runtime.status_callback = MagicMock()
    with patch(
        'backend.execution.runtime_mixins.git_setup.call_sync_from_async',
        new_callable=AsyncMock,
    ):
        result = await runtime.clone_or_init_repo(None, 'owner/repo', 'main')
    assert result == 'repo'
    runtime.status_callback.assert_called()
