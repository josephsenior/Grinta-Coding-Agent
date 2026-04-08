"""Helpers for adapting tool prompts to the active terminal runtime."""

import functools
import shutil
import subprocess
import sys


@functools.cache
def uses_powershell_terminal() -> bool:
    """Return True when the active terminal contract should be PowerShell.

    Aligns with ``ToolRegistry._detect_shell`` by verifying that bash
    actually works (not only present on PATH).  The result is cached
    for the lifetime of the process.
    """
    if not sys.platform.lower().startswith('win'):
        return False
    bash_path = shutil.which('bash')
    if not bash_path:
        return True
    # Verify bash actually works — mirrors ToolRegistry._check_command logic
    try:
        result = subprocess.run(
            ['bash', '--version'],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode != 0
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return True


def get_shell_name() -> str:
    """Return the shell name that matches the runtime terminal contract."""
    return 'powershell' if uses_powershell_terminal() else 'bash'


def get_terminal_tool_name() -> str:
    """Return the terminal tool name that matches the runtime shell."""
    return 'execute_powershell' if uses_powershell_terminal() else 'execute_bash'
