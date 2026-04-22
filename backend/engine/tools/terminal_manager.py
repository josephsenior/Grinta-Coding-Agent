from typing import Any

from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)

TERMINAL_MANAGER_TOOL_NAME = 'terminal_manager'


def create_terminal_manager_tool() -> dict[str, Any]:
    return {
        'type': 'function',
        'function': {
            'name': TERMINAL_MANAGER_TOOL_NAME,
            'description': (
                'Manage interactive PTY terminal sessions: open a new session, send input, '
                'or read output buffers. '
                'Minimal smoke test: action=open with a short, bounded command (e.g. '
                'print host name), then action=read with the returned session_id; use '
                'action=input only when you need extra keys or an interactive program. '
                'Long-running servers are optional — not required to verify the tool.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['open', 'input', 'read'],
                        'description': "The action to perform. 'open' to start a command. 'input' to send text/control-c. 'read' to view output.",
                    },
                    'session_id': {
                        'type': 'string',
                        'description': "The session ID. Required for 'input' and 'read' actions.",
                    },
                    'command': {
                        'type': 'string',
                        'description': "The command to start the session. Required for 'open' action.",
                    },
                    'cwd': {
                        'type': 'string',
                        'description': 'Optional working directory for the session.',
                    },
                    'rows': {
                        'type': 'integer',
                        'description': (
                            'Optional TTY height (1–500). If set, ``cols`` must be '
                            'set too. Applied on open, or before input/read when '
                            'using the ``input`` / ``read`` action.'
                        ),
                    },
                    'cols': {
                        'type': 'integer',
                        'description': (
                            'Optional TTY width (1–2000). If set, ``rows`` must be '
                            'set too.'
                        ),
                    },
                    'input': {
                        'type': 'string',
                        'description': (
                            "Text to send. For the 'input' action, provide this "
                            'and/or ``control`` and/or ``rows``+``cols``.'
                        ),
                    },
                    'is_control': {
                        'type': 'boolean',
                        'description': "Set to true if sending a control character sequence like 'C-c' via ``input``.",
                    },
                    'control': {
                        'type': 'string',
                        'description': (
                            'Optional named control (e.g. C-c, esc, enter). Shorthand '
                            'instead of ``input`` with ``is_control`` true.'
                        ),
                    },
                },
                'required': ['action'],
            },
        },
    }


def _opt_int(v: object) -> int | None:
    if v is None or v == '':
        return None
    return int(v)


def handle_terminal_manager_tool(arguments: dict) -> Any:
    """Route terminal manager intents back into the core backend actions."""
    action = arguments.get('action')

    if action == 'open':
        cmd = arguments.get('command')
        if not cmd:
            raise ValueError("Terminal 'open' action requires 'command'")
        return TerminalRunAction(
            command=cmd,
            cwd=arguments.get('cwd'),
            rows=_opt_int(arguments.get('rows')),
            cols=_opt_int(arguments.get('cols')),
        )

    elif action == 'input':
        session_id = arguments.get('session_id')
        input_val = arguments.get('input', '') or ''
        control_val = arguments.get('control')
        rows, cols = _opt_int(arguments.get('rows')), _opt_int(arguments.get('cols'))
        if not session_id:
            raise ValueError("Terminal 'input' action requires 'session_id'")
        if (
            not str(input_val).strip()
            and not (control_val and str(control_val).strip())
            and rows is None
        ):
            raise ValueError(
                "Terminal 'input' action requires 'input' and/or 'control' and/or "
                "'rows' + 'cols'"
            )

        is_control = arguments.get('is_control', False)
        if isinstance(is_control, str):
            is_control = is_control.lower() == 'true'

        return TerminalInputAction(
            session_id=session_id,
            input=str(input_val),
            is_control=is_control,
            control=str(control_val) if control_val is not None else None,
            rows=rows,
            cols=cols,
        )

    elif action == 'read':
        session_id = arguments.get('session_id')
        if not session_id:
            raise ValueError("Terminal 'read' action requires 'session_id'")
        return TerminalReadAction(
            session_id=session_id,
            rows=_opt_int(arguments.get('rows')),
            cols=_opt_int(arguments.get('cols')),
        )

    raise ValueError(f'Unknown terminal manager action: {action}')
