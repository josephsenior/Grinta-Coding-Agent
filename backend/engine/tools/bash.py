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
from backend.engine.tools.prompt import get_shell_name, get_terminal_tool_name

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
    'Execute a {shell} command in a persistent shell session.\n\n'
    '* **Discovery & reading project files:** use `analyze_project_structure`, `search_code`, '
    'or `str_replace_editor` (`view_file`)—not `cat`/`grep`/`find` for source and config under the repo.\n'
    '* One command at a time. Chain with `&&` or `;`.\n'
    '* Persistent: env vars, venvs, cwd persist between calls.\n'
    '* Do NOT use `set -e` / `set -eu` / `set -euo pipefail`.\n'
    '* Long-running: background with `cmd > out.log 2>&1 &`, or set `timeout`.\n'
    '* Exit code `-1`: process still running. Set `is_input=true` to send input, '
    'empty string for more logs, or `C-c`/`C-d`/`C-z` to interrupt.\n'
    "* Do NOT create/write files with this tool — use `str_replace_editor(command='create')` instead.\n"
    '* Shell cwd is the **project root** (see runtime). Prefer relative paths (`dir/file`, `./script`). '
    'There is no `/workspace` alias — use real relative or absolute paths.\n'
    '* In bash, never glue a folder name to a Windows drive letter: use `dir/C:/path` or quotes, '
    'not `dirC:/path`.\n'
)
_SHORT_BASH_DESCRIPTION = (
    'Execute a {shell} command. Prefer `search_code` / `analyze_project_structure` / editor `view_file` '
    'for repo reads—not cat/grep. Chain with `&&`/`;`. '
    'Background long-running commands with `cmd > out.log 2>&1 &`. '
    'Exit code -1 means still running — set is_input=true to interact. '
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
    ).format(shell=shell)

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
                'type': 'string',
                'enum': ['true', 'false'],
                'description': 'If True, run the command in a background shell session. Returns immediately with a session ID. Use for long-running processes like servers or build watchers.',
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
        required=['command'],
    )
