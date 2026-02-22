"""Bash execution tool used by the CodeAct agent."""

from __future__ import annotations

from typing import Any

from backend.engines.orchestrator.tools.common import (
    create_tool_definition,
    get_command_param,
    get_is_input_param,
    get_security_risk_param,
    get_timeout_param,
)
from backend.engines.orchestrator.tools.prompt import refine_prompt
from backend.llm.tool_names import EXECUTE_BASH_TOOL_NAME

ChatCompletionToolParam = Any

_DETAILED_BASH_DESCRIPTION = (
    "Execute a bash command in the terminal within a persistent shell session.\n\n\n"
    "### Command Execution\n"
    "* One command at a time: You can only execute one bash command at a time. "
    "If you need to run multiple commands sequentially, use `&&` or `;` to chain them together.\n"
    "* Persistent session: Commands execute in a persistent shell session where environment variables, "
    "virtual environments, and working directory persist between commands.\n"
    "* Soft timeout: Commands have a soft timeout of 10 seconds, once that's reached, "
    "you have the option to continue or interrupt the command (see section below for details)\n"
    "* Shell options: Do NOT use `set -e`, `set -eu`, or `set -euo pipefail` in shell scripts "
    "or commands in this environment. The runtime may not support them and can cause unusable shell sessions. "
    "If you want to run multi-line bash commands, write the commands to a file and then run it, instead.\n\n"
    "### Long-running Commands\n"
    "* For commands that may run indefinitely, run them in the background and redirect output to a file, "
    "e.g. `python3 app.py > server.log 2>&1 &`.\n"
    "* For commands that may run for a long time (e.g. installation or testing commands), "
    'or commands that run for a fixed amount of time (e.g. sleep), you should set the "timeout" parameter '
    "of your function call to an appropriate value.\n"
    "* If a bash command returns exit code `-1`, this means the process hit the soft timeout and is not yet finished. "
    "By setting `is_input` to `true`, you can:\n"
    "  - Send empty `command` to retrieve additional logs\n"
    "  - Send text (set `command` to the text) to STDIN of the running process\n"
    "  - Send control commands like `C-c` (Ctrl+C), `C-d` (Ctrl+D), or `C-z` (Ctrl+Z) to interrupt the process\n"
    '  - If you do C-c, you can re-start the process with a longer "timeout" parameter to let it run to completion\n\n'
    "### Best Practices\n"
    "* Directory verification: Before creating new directories or files, first verify the parent directory exists "
    "and is the correct location.\n"
    "* Directory management: Try to maintain working directory by using absolute paths and avoiding excessive use of `cd`.\n\n"
    "### Output Handling\n"
    "* Output truncation: If the output exceeds a maximum length, it will be truncated before being returned.\n"
)
_SHORT_BASH_DESCRIPTION = (
    "Execute a bash command in the terminal.\n"
    "* Long running commands: For commands that may run indefinitely, it should be run in the background "
    "and the output should be redirected to a file, e.g. command = `python3 app.py > server.log 2>&1 &`. "
    'For commands that need to run for a specific duration, you can set the "timeout" argument to specify a hard timeout in seconds.\n'
    "* Interact with running process: If a bash command returns exit code `-1`, this means the process is not yet finished. "
    "By setting `is_input` to `true`, the assistant can interact with the running process and send empty `command` "
    "to retrieve any additional logs, or send additional text (set `command` to the text) to STDIN of the running process, "
    "or send command like `C-c` (Ctrl+C), `C-d` (Ctrl+D), `C-z` (Ctrl+Z) to interrupt the process.\n"
    "* One command at a time: You can only execute one bash command at a time. "
    "If you need to run multiple commands sequentially, you can use `&&` or `;` to chain them together."
)


def create_cmd_run_tool(use_short_description: bool = False):
    """Create a bash command execution tool for the agent.

    Args:
        use_short_description: Whether to use short or detailed description.

    Returns:
        ChatCompletionToolParam: The configured bash command tool.

    """
    description = (
        _SHORT_BASH_DESCRIPTION if use_short_description else _DETAILED_BASH_DESCRIPTION
    )
    return create_tool_definition(
        name=EXECUTE_BASH_TOOL_NAME,
        description=refine_prompt(description),
        properties={
            "command": get_command_param(
                refine_prompt(
                    "The bash command to execute. Can be empty string to view additional logs when previous exit code is `-1`. Can be `C-c` (Ctrl+C) to interrupt the currently running process. Note: You can only execute one bash command at a time. If you need to run multiple commands sequentially, you can use `&&` or `;` to chain them together.",
                ),
            ),
            "is_input": get_is_input_param(
                refine_prompt(
                    "If True, the command is an input to the running process. If False, the command is a bash command to be executed in the terminal. Default is False.",
                ),
            ),
            "is_background": {
                "type": "boolean",
                "description": refine_prompt(
                    "If True, run the command in a background shell session. Returns immediately with a session ID. Use for long-running processes like servers or build watchers.",
                ),
            },
            "grep_pattern": {
                "type": "string",
                "description": refine_prompt(
                    "Optional regex pattern to filter the command output. Only lines matching this pattern will be included in the response. Use this to reduce noise from large outputs.",
                ),
            },
            "timeout": get_timeout_param(
                "Optional. Sets a hard timeout in seconds for the command execution. If not provided, the command will use the default soft timeout behavior.",
            ),
            "security_risk": get_security_risk_param(),
        },
        required=["command"],
    )
