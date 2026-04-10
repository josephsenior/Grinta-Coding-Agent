"""Helpers for adapting tool prompts to the active terminal runtime."""

import base64
import functools
import sys


def _runtime_prefers_powershell() -> bool:
    """Mirror runtime shell-session selection for prompt-side tool generation."""
    from backend.execution.utils.tool_registry import ToolRegistry

    registry = ToolRegistry()
    return not registry.has_bash


@functools.cache
def uses_powershell_terminal() -> bool:
    """Return True when the active terminal contract should be PowerShell.

    Aligns with ``create_shell_session()`` by asking the same ToolRegistry-
    based question the runtime uses on Windows: prefer bash when available,
    otherwise fall back to PowerShell. The result is cached for the lifetime
    of the process.
    """
    if not sys.platform.lower().startswith('win'):
        return False
    return _runtime_prefers_powershell()


def get_shell_name() -> str:
    """Return the shell name that matches the runtime terminal contract."""
    return 'powershell' if uses_powershell_terminal() else 'bash'


def is_windows_with_bash() -> bool:
    """True when running on Windows but using Git Bash as the active shell."""
    return sys.platform == 'win32' and not uses_powershell_terminal()


def get_python_shell_command() -> str:
    """Return the preferred Python executable for the active shell contract."""
    if uses_powershell_terminal():
        return 'python'
    return 'python3'


def build_python_exec_command(script: str) -> str:
    """Return a shell-safe Python command that executes a base64-encoded script."""
    encoded = base64.b64encode(script.encode()).decode()
    py_expr = f"import base64;exec(base64.b64decode(b'{encoded}').decode())"

    if uses_powershell_terminal():
        return (
            f"if (Get-Command python -ErrorAction SilentlyContinue) {{ python -c \"{py_expr}\" }} "
            f"elseif (Get-Command py -ErrorAction SilentlyContinue) {{ py -3 -c \"{py_expr}\" }} "
            f"elseif (Get-Command python3 -ErrorAction SilentlyContinue) {{ python3 -c \"{py_expr}\" }} "
            f"else {{ Write-Output '[MISSING_TOOL] python/python3/py not found in PATH'; exit 127 }}"
        )

    return (
        "if command -v python3 >/dev/null 2>&1; then "
        f"python3 -c \"{py_expr}\"; "
        "elif command -v python >/dev/null 2>&1; then "
        f"python -c \"{py_expr}\"; "
        "elif command -v py >/dev/null 2>&1; then "
        f"py -3 -c \"{py_expr}\"; "
        "else echo '[MISSING_TOOL] python/python3/py not found in PATH'; exit 127; fi"
    )


def get_terminal_tool_name() -> str:
    """Return the terminal tool name that matches the runtime shell."""
    return 'execute_powershell' if uses_powershell_terminal() else 'execute_bash'
