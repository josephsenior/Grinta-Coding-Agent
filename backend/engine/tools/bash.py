"""Bash execution tool used by the Orchestrator agent."""

from __future__ import annotations

import re
from typing import Any

from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_is_input_param,
    get_security_risk_param,
    get_timeout_param,
)
from backend.utils.terminal.terminal_contract import (
    get_shell_name,
    get_terminal_tool_name,
    is_windows_with_bash,
    uses_powershell_terminal,
)

ChatCompletionToolParam = Any

# e.g. ``componentsC:/Users/...`` (missing ``/`` before the drive letter)
_WINDOWS_DRIVE_GLUED_RE = re.compile(r'[A-Za-z0-9_]C:/', re.IGNORECASE)


def windows_drive_glued_in_command(command: str) -> bool:
    """True when a path token looks like a dirname glued to a Windows drive (``fooC:/``)."""
    if not command or not isinstance(command, str):
        return False
    return _WINDOWS_DRIVE_GLUED_RE.search(command) is not None


def windows_drive_glued_hint() -> str:
    """Short hint for the reasoning line when a command may have a glued Windows path."""
    return (
        '[SHELL] Possible typo: a folder name may be glued to a Windows drive '
        '(e.g. componentsC:/...). Insert a separator: components/C:/... or quote the path.'
    )


_DETAILED_BASH_DESCRIPTION = (
    'Execute a **one-shot** {shell} command synchronously. '
    'Use for build, test, install, git, and file-system commands.\n\n'
    '**When to use `{shell}` vs `terminal_manager`**\n'
    '* `{shell}` — one-shot commands: tests, installs, builds, git, discovery. '
    'Use `is_background=true` for servers or build watchers.\n'
    '* `terminal_manager` — interactive programs: REPLs, ssh, `python -i`, '
    'programs that ask questions; or reading output from a detached background session.\n\n'
    '* Prefer `grep`, `glob`, `find_symbols`, `read` over shell commands for repo discovery.\n'
    '* One command per call. Chain with `&&` or `;` when needed.\n'
    '* Persistent: env vars, venvs, cwd survive across calls.\n'
    '* Do NOT use `set -e` / `set -eu` / `set -euo pipefail`.\n'
    '* Long-running: pass an explicit `timeout` or use `is_background=true`.\n'
    '* Do NOT create/write files — use `create`, `replace_string`, `edit_symbol`, or `multiedit`.\n'
    '* Shell cwd is the **project root**. Prefer relative paths (`./script`). '
    'There is no `/workspace` alias.\n'
    '* In bash, never glue a folder name to a Windows drive: use `dir/C:/path`, not `dirC:/path`.\n'
)
_SHORT_BASH_DESCRIPTION = (
    'Execute a **one-shot** {shell} command synchronously. '
    'Use `{shell}` for builds, tests, installs, git — short commands. '
    'Prefer `grep`/`glob`/`read` for repo discovery. '
    'Chain with `&&`/`;`. Use `is_background=true` for servers/build watchers. '
    'For interactive programs (REPLs, ssh, `python -i`) use `terminal_manager`. '
    'Do not glue paths to Windows drives (`dirC:/`); use `dir/C:/` or quotes.'
)


def create_cmd_run_tool(use_short_description: bool = False):
    """Create a bash/powershell command execution tool for the agent.

    Args:
        use_short_description: Whether to use short or detailed description.

    Returns:
        ChatCompletionToolParam: The configured command tool.

    """
    shell = get_shell_name()
    tool_name = get_terminal_tool_name()

    description = (
        _SHORT_BASH_DESCRIPTION if use_short_description else _DETAILED_BASH_DESCRIPTION
    ).format(shell=shell)  # nosec B604 (formatting tool description, not executing)

    # Explicit identity note for Windows + Git Bash / PowerShell to prevent shell confusion
    if uses_powershell_terminal():
        description += (
            '\n* **IMPORTANT — PowerShell on Windows:** This terminal runs PowerShell, '
            'NOT Bash. DO NOT use these FORBIDDEN commands: grep, ls, cat, find, echo, mkdir, rm, pwd, which, chmod, sed, awk. '
            'Use PowerShell native cmdlets or Python. Windows paths (C:\\...) are normal.'
        )
    elif is_windows_with_bash():
        description += (
            '\n* **IMPORTANT — Git Bash on Windows:** This terminal runs Git Bash, '
            'NOT PowerShell. Use only bash commands. DO NOT use these FORBIDDEN PowerShell '
            'cmdlets: Get-ChildItem, Get-Process, Get-Content, Select-String, Write-Output, '
            'Set-Location, ForEach-Object, Where-Object, $PSVersionTable. '
            'Use `python` (not `python3`). Windows paths (C:\\...) in output are normal.'
        )
    else:
        description += (
            '\n* **IMPORTANT — Bash:** This terminal runs Bash, NOT PowerShell. '
            'DO NOT use these FORBIDDEN PowerShell cmdlets: Get-ChildItem, Get-Process, '
            'Get-Content, Select-String, Write-Output, Set-Location, ForEach-Object, '
            'Where-Object, $PSVersionTable.'
        )

    return create_tool_definition(
        name=tool_name,
        description=description,
        properties={
            'command': get_command_param(
                f'The {shell} command to execute. Empty string for more logs when exit code is -1. `C-c` to interrupt.',
            ),
            'truncation_strategy': {
                'type': 'string',
                'enum': ['tail_heavy', 'head_heavy', 'balanced'],
                'description': "How to truncate long output. 'tail_heavy' (default) keeps the end of the log in case of error. 'head_heavy' keeps the beginning. 'balanced' keeps both.",
            },
            'is_input': get_is_input_param(
                f'If True, the command is an input to the running process. If False, the command is a {shell} command to be executed in the terminal. Default is False.'
            ),
            'is_background': {
                'type': 'boolean',
                'description': 'If true, run the command in a background shell session. Returns immediately with a session ID. Use for long-running processes like servers or build watchers.',
            },
            'grep_pattern': {
                'type': 'string',
                'description': 'Optional regex pattern to filter the command output. Only lines matching this pattern will be included in the response. Use this to reduce noise from large outputs.',
            },
            'timeout': get_timeout_param(
                'Optional. Sets a hard timeout in seconds for the command execution. If not provided, the command will use the default soft timeout behavior.',
            ),
            'security_risk': get_security_risk_param(),
        },
        required=['command', 'security_risk'],
    )
