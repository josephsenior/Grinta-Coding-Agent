"""Helpers for adapting tool prompts to the active terminal runtime."""

import shutil
import sys


def uses_powershell_terminal() -> bool:
    """Return True when the active terminal contract should be PowerShell."""
    return sys.platform.lower().startswith('win') and not shutil.which('bash')


def get_shell_name() -> str:
    """Return the shell name that matches the runtime terminal contract."""
    return 'powershell' if uses_powershell_terminal() else 'bash'


def get_terminal_tool_name() -> str:
    """Return the terminal tool name that matches the runtime shell."""
    return 'execute_powershell' if uses_powershell_terminal() else 'execute_bash'
