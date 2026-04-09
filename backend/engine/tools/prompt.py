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
    """Return the Python executable name that matches the active shell contract."""
    # Windows always installs Python as 'python', even inside Git Bash.
    if sys.platform == 'win32':
        return 'python'
    return 'python3'


def build_python_exec_command(script: str) -> str:
    """Return a shell-safe Python command that executes a base64-encoded script."""
    encoded = base64.b64encode(script.encode()).decode()
    python_cmd = get_python_shell_command()
    return (
        f"{python_cmd} -c \"import base64;"
        f"exec(base64.b64decode(b'{encoded}').decode())\""
    )


def get_terminal_tool_name() -> str:
    """Return the terminal tool name that matches the runtime shell."""
    return 'execute_powershell' if uses_powershell_terminal() else 'execute_bash'
