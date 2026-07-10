from typing import Any

from backend.core.tools.tool_names import TERMINAL_TOOL_NAME
from backend.engine.tools.param_defs import (
    get_security_risk_param,
    get_timeout_param,
)
from backend.utils.terminal.terminal_contract import (
    get_shell_name,
    is_windows_with_bash,
    uses_powershell_terminal,
)

_DETAILED_TERMINAL_DESCRIPTION = (
    'Omnipotent terminal tool for both one-shot commands and interactive PTY sessions using {shell}.\n\n'
    '**Actions**\n'
    '* `run` — execute a one-shot command synchronously (builds, tests, git, discovery). '
    'Will auto-background if it hangs.\n'
    '* `start` — open an interactive PTY session and run a command.\n'
    '* `read` — fetch output from an interactive or background session (`mode=delta` preferred).\n'
    '* `input` — send follow-up keystrokes/commands to a session.\n'
    '* `wait` — block until regex `pattern` matches or `timeout` expires.\n'
    '* `kill` — release/stop a session immediately.\n\n'
)

def create_terminal_tool() -> dict[str, Any]:
    shell = get_shell_name()
    description = _DETAILED_TERMINAL_DESCRIPTION.format(shell=shell)

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

    return {
        'type': 'function',
        'function': {
            'name': TERMINAL_TOOL_NAME,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'run',
                            'start',
                            'input',
                            'read',
                            'wait',
                            'kill',
                        ],
                        'description': (
                            "'run': synchronous one-shot command execution. "
                            "'start': start interactive PTY session. "
                            "'read': fetch output (delta=new since cursor). "
                            "'wait': block until `pattern` matches or `timeout` expires. "
                            "'input': send more text/control to the same session. "
                            "'kill': release the session immediately."
                        ),
                    },
                    'session_id': {
                        'type': 'string',
                        'description': (
                            'Session id from `start`, `is_background=true`, or idle detach '
                            '(e.g. `bg-a1b2c3d4`). Required for input/read/wait/kill.'
                        ),
                    },
                    'command': {
                        'type': 'string',
                        'description': (
                            "Required for 'run' and 'start'. The command to execute."
                        ),
                    },
                    'cwd': {
                        'type': 'string',
                        'description': 'Optional working directory for the command or session.',
                    },
                    'is_background': {
                        'type': 'boolean',
                        'description': 'For action=run: run the command in a background shell session. Returns immediately with a session ID.',
                    },
                    'grep_pattern': {
                        'type': 'string',
                        'description': 'For action=run: optional regex pattern to filter the output.',
                    },
                    'truncation_strategy': {
                        'type': 'string',
                        'enum': ['tail_heavy', 'head_heavy', 'balanced'],
                        'description': 'For action=run: how to truncate long output.',
                    },
                    'rows': {
                        'type': 'integer',
                        'description': 'Optional TTY height.',
                    },
                    'cols': {
                        'type': 'integer',
                        'description': 'Optional TTY width.',
                    },
                    'input': {
                        'type': 'string',
                        'description': "For 'input': text to inject into the shell.",
                    },
                    'is_control': {
                        'type': 'boolean',
                        'description': "Set to true if sending a control character sequence like 'C-c' via `input`.",
                    },
                    'submit': {
                        'type': 'boolean',
                        'description': "For action='input': when true (default), append a newline.",
                    },
                    'control': {
                        'type': 'string',
                        'description': "Named control for 'input' (e.g. C-c, esc, enter).",
                    },
                    'offset': {
                        'type': 'integer',
                        'description': "For action='read' with mode='delta': byte offset.",
                    },
                    'mode': {
                        'type': 'string',
                        'enum': ['delta', 'snapshot'],
                        'description': "For action='read'.",
                    },
                    'pattern': {
                        'type': 'string',
                        'description': "For action='wait': case-insensitive regex.",
                    },
                    'timeout': get_timeout_param(
                        'Optional. Seconds to wait for `pattern` before timeout, or max execution time for run.',
                    ),
                    'security_risk': get_security_risk_param(),
                },
                'required': ['action'],
                'allOf': [
                    {
                        'if': {'properties': {'action': {'enum': ['run', 'start']}}},
                        'then': {'required': ['command', 'security_risk']},
                    },
                    {
                        'if': {
                            'properties': {
                                'action': {
                                    'enum': [
                                        'input',
                                        'read',
                                        'wait',
                                        'kill',
                                    ]
                                }
                            }
                        },
                        'then': {'required': ['session_id']},
                    },
                    {
                        'if': {'properties': {'action': {'const': 'wait'}}},
                        'then': {'required': ['pattern']},
                    },
                ],
            },
        },
    }
