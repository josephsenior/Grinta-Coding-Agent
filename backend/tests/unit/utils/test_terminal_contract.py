"""Unit tests for terminal runtime prompt adaptation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.utils.terminal.terminal_contract import (
    _runtime_prefers_powershell,
    build_python_exec_command,
    get_active_tool_registry,
    get_python_shell_command,
    get_shell_name,
    get_terminal_tool_name,
    is_windows_with_bash,
    set_active_tool_registry,
    uses_powershell_terminal,
)


@pytest.fixture(autouse=True)
def clean_registry():
    set_active_tool_registry(None)
    yield
    set_active_tool_registry(None)


def test_active_tool_registry_context() -> None:
    assert get_active_tool_registry() is None

    mock_reg = MagicMock()
    set_active_tool_registry(mock_reg)
    assert get_active_tool_registry() is mock_reg


def test_runtime_prefers_powershell() -> None:
    # 1. Active registry
    mock_reg = MagicMock()
    mock_reg.has_bash = True
    mock_reg.has_powershell = False

    set_active_tool_registry(mock_reg)
    assert _runtime_prefers_powershell() is False

    mock_reg.has_bash = False
    mock_reg.has_powershell = True
    assert _runtime_prefers_powershell() is True

    # 2. Fallback to global registry
    set_active_tool_registry(None)
    mock_global = MagicMock()
    mock_global.has_bash = True
    mock_global.has_powershell = False
    with patch(
        'backend.utils.terminal.terminal_contract._get_global_tool_registry',
        return_value=mock_global,
    ):
        assert _runtime_prefers_powershell() is False


def test_uses_powershell_terminal() -> None:
    # 1. Non-Windows always returns False
    with patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_os_caps:
        mock_os_caps.is_windows = False
        assert uses_powershell_terminal() is False

    # 2. Windows delegates to prefers_powershell
    with patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_os_caps:
        mock_os_caps.is_windows = True
        with patch(
            'backend.utils.terminal.terminal_contract._runtime_prefers_powershell',
            return_value=True,
        ):
            assert uses_powershell_terminal() is True
        with patch(
            'backend.utils.terminal.terminal_contract._runtime_prefers_powershell',
            return_value=False,
        ):
            assert uses_powershell_terminal() is False


def test_get_shell_name() -> None:
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=True,
    ):
        assert get_shell_name() == 'powershell'
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        assert get_shell_name() == 'bash'


def test_is_windows_with_bash() -> None:
    with patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_os_caps:
        mock_os_caps.is_windows = True
        with patch(
            'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
            return_value=False,
        ):
            assert is_windows_with_bash() is True

    with patch('backend.utils.terminal.terminal_contract.OS_CAPS') as mock_os_caps:
        mock_os_caps.is_windows = False
        assert is_windows_with_bash() is False


def test_get_python_shell_command() -> None:
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=True,
    ):
        assert get_python_shell_command() == 'python'
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        assert get_python_shell_command() == 'python3'


def test_build_python_exec_command() -> None:
    script = "print('hello')"

    # 1. PowerShell
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=True,
    ):
        cmd = build_python_exec_command(script)
        assert 'python -c' in cmd
        assert 'base64' in cmd

    # 2. Bash
    with patch(
        'backend.utils.terminal.terminal_contract.uses_powershell_terminal',
        return_value=False,
    ):
        cmd = build_python_exec_command(script)
        assert 'if command -v python3' in cmd


def test_get_terminal_tool_name() -> None:
    assert get_terminal_tool_name() == 'terminal'
