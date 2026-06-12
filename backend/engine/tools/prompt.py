"""Backward-compatible re-export of terminal runtime helper functions."""

from backend.utils.terminal_contract import (
    OS_CAPS,
    _get_global_tool_registry,
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

__all__ = [
    'OS_CAPS',
    '_get_global_tool_registry',
    '_runtime_prefers_powershell',
    'build_python_exec_command',
    'get_active_tool_registry',
    'get_python_shell_command',
    'get_shell_name',
    'get_terminal_tool_name',
    'is_windows_with_bash',
    'set_active_tool_registry',
    'uses_powershell_terminal',
]
