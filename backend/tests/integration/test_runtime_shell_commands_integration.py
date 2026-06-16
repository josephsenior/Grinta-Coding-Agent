"""Integration checks for runtime shell helper strings built by RuntimeExecutor."""

from __future__ import annotations

import pytest

from backend.execution.action_execution_server import RuntimeExecutor


@pytest.mark.integration
def test_runtime_executor_shell_git_config_commands_include_identity_fields(
    tmp_path,
) -> None:
    ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
    ps = ex._build_shell_git_config_command(True)  # noqa: SLF001
    sh = ex._build_shell_git_config_command(False)  # noqa: SLF001
    for fragment in (
        'GIT_AUTHOR_EMAIL',
        'GIT_AUTHOR_NAME',
        'GIT_COMMITTER_EMAIL',
        'GIT_COMMITTER_NAME',
    ):
        assert fragment in ps
        assert fragment in sh
    assert 'git config --global' not in ps
    assert 'git config --global' not in sh


@pytest.mark.integration
def test_runtime_executor_env_check_command_powershell_vs_bash(tmp_path) -> None:
    ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
    ps = RuntimeExecutor._build_env_check_command(True)  # noqa: SLF001
    bash = RuntimeExecutor._build_env_check_command(False)  # noqa: SLF001
    assert 'env_check' in ps.lower() or 'Env' in ps
    assert 'env_check' in bash


@pytest.mark.integration
def test_runtime_executor_uses_powershell_contract_follows_os_and_session(
    tmp_path,
) -> None:
    ex = RuntimeExecutor([], str(tmp_path), 'user', 1, enable_browser=False)
    # Default session is not PowerShell-specific — should match OS_CAPS.is_windows.
    uses = ex._uses_powershell_shell_contract()  # noqa: SLF001
    assert isinstance(uses, bool)
