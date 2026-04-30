"""Unit tests for backend.execution.sandboxing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.execution.sandboxing import (
    ExecutionSandboxPolicy,
    is_sandboxed_local_profile,
    is_workspace_restricted_profile,
    resolve_execution_sandbox_policy,
)


def test_is_sandboxed_local_profile() -> None:
    assert is_sandboxed_local_profile(None) is False
    assert (
        is_sandboxed_local_profile(SimpleNamespace(execution_profile='standard'))
        is False
    )
    assert (
        is_sandboxed_local_profile(SimpleNamespace(execution_profile='sandboxed_local'))
        is True
    )


def test_is_workspace_restricted_profile() -> None:
    assert is_workspace_restricted_profile(None) is False
    assert (
        is_workspace_restricted_profile(
            SimpleNamespace(execution_profile='hardened_local')
        )
        is True
    )
    assert (
        is_workspace_restricted_profile(
            SimpleNamespace(execution_profile='sandboxed_local')
        )
        is True
    )


def test_resolve_policy_returns_none_when_not_sandboxed_local() -> None:
    assert (
        resolve_execution_sandbox_policy(
            security_config=SimpleNamespace(execution_profile='standard'),
            workspace_root='C:/ws',
        )
        is None
    )


def test_execution_sandbox_policy_wrap_appcontainer_argv() -> None:
    p = ExecutionSandboxPolicy(
        backend='appcontainer',
        workspace_root='C:/ws',
        allow_network=False,
    )
    out = p.wrap_argv(['echo', 'hi'], cwd='C:/ws')
    joined = ' '.join(out)
    assert '-m' in out and 'appcontainer_runner' in joined
    assert '--' in out


def test_execution_sandbox_policy_bubblewrap_requires_bwrap() -> None:
    p = ExecutionSandboxPolicy(
        backend='bubblewrap',
        workspace_root='/ws',
        allow_network=True,
    )
    with (
        patch('backend.execution.sandboxing.shutil.which', return_value=None),
        pytest.raises(RuntimeError, match='bubblewrap'),
    ):
        p.wrap_argv(['true'], cwd='/ws')


def test_execution_sandbox_policy_sandbox_exec_requires_tool() -> None:
    p = ExecutionSandboxPolicy(
        backend='sandbox-exec',
        workspace_root='/private/ws',
        allow_network=False,
    )
    with (
        patch('backend.execution.sandboxing.shutil.which', return_value=None),
        pytest.raises(RuntimeError, match='sandbox-exec'),
    ):
        p.wrap_argv(['true'], cwd='/private/ws')


def test_resolve_execution_sandbox_policy_windows_branch(tmp_path) -> None:
    caps = SimpleNamespace(is_linux=False, is_macos=False, is_windows=True)
    with patch('backend.execution.sandboxing.OS_CAPS', caps):
        cfg = SimpleNamespace(
            execution_profile='sandboxed_local',
            allow_network_commands=False,
        )
        pol = resolve_execution_sandbox_policy(
            security_config=cfg,
            workspace_root=str(tmp_path),
        )
    assert pol is not None
    assert pol.backend == 'appcontainer'


def test_resolve_execution_sandbox_policy_unsupported_platform() -> None:
    caps = SimpleNamespace(is_linux=False, is_macos=False, is_windows=False)
    with (
        patch('backend.execution.sandboxing.OS_CAPS', caps),
        patch('backend.execution.sandboxing.sys.platform', 'freebsd'),
    ):
        cfg = SimpleNamespace(execution_profile='sandboxed_local')
        with pytest.raises(RuntimeError, match='not supported'):
            resolve_execution_sandbox_policy(security_config=cfg, workspace_root='/tmp')
