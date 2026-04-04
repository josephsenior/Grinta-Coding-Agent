"""Bash execution tool used by the Orchestrator agent."""

from __future__ import annotations

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

_DETAILED_BASH_DESCRIPTION = (
    'Execute a {shell} command in a persistent shell session.\n\n'
    '* One command at a time. Chain with `&&` or `;`.\n'
    '* Persistent: env vars, venvs, cwd persist between calls.\n'
    '* Do NOT use `set -e` / `set -eu` / `set -euo pipefail`.\n'
    '* Long-running: background with `cmd > out.log 2>&1 &`, or set `timeout`.\n'
    '* Exit code `-1`: process still running. Set `is_input=true` to send input, '
    'empty string for more logs, or `C-c`/`C-d`/`C-z` to interrupt.\n'
    "* Do NOT create/write files with this tool — use `str_replace_editor(command='create')` instead.\n"
    '* Use absolute paths. Verify parent dirs before creating files/dirs.\n'
)
_SHORT_BASH_DESCRIPTION = (
    'Execute a {shell} command. Chain with `&&`/`;`. '
    'Background long-running commands with `cmd > out.log 2>&1 &`. '
    'Exit code -1 means still running — set is_input=true to interact.'
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
