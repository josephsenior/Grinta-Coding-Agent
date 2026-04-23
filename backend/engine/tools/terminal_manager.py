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
                'Interactive PTY terminal (same session across open → read → input). '
                'action=open runs ``command`` once (a newline is appended server-side—'
                'the shell executes it immediately on PowerShell and bash). Then use '
                'action=read (prefer mode=delta; reuse next_offset from the last result, '
                'or omit offset on read to continue from the server cursor) before sending '
                'more input. For a second command in the same session, use action=input '
                'with the next line (e.g. ``dir`` or ``ls``), not repeated blank Enter/control '
                'unless you are diagnosing a hung prompt. Do not spam identical control/input '
                'when reads show no new bytes. On Windows the shell is often PowerShell—use '
                'PowerShell cmdlets, not Unix-only tools, unless you know the session is bash.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['open', 'input', 'read'],
                        'description': (
                            "'open': start session and run ``command`` once (already submitted). "
                            "'read': fetch output (delta=new since cursor; snapshot=full buffer). "
                            "'input': send more text or a named ``control`` (e.g. enter, C-c)."
                        ),
                    },
                    'session_id': {
                        'type': 'string',
                        'description': "The session ID returned by action='open'. Required for 'input' and 'read'.",
                    },
                    'command': {
                        'type': 'string',
                        'description': (
                            "Required for 'open': first command line for this session. "
                            'It is executed immediately (newline added by the runtime). '
                            'Follow-up commands belong in action=input, not repeated opens.'
                        ),
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
                            "For 'input': text to inject into the shell (e.g. ``Get-ChildItem`` "
                            'or ``dir``). Use this for the second and later commands in the '
                            'same session. Avoid sending only blank lines unless you intend '
                            'to submit an empty line to the shell.'
                        ),
                    },
                    'is_control': {
                        'type': 'boolean',
                        'description': "Set to true if sending a control character sequence like 'C-c' via ``input``.",
                    },
                    'submit': {
                        'type': 'boolean',
                        'description': (
                            "For action='input': when true (default), append a newline to "
                            'non-control ``input`` if it does not already end with one. '
                            'Set false for passwords or partial input before Enter.'
                        ),
                    },
                    'control': {
                        'type': 'string',
                        'description': (
                            "Named control for 'input' (e.g. C-c, esc, enter). Repeated "
                            'enter with no new shell output usually means you need a real '
                            'command in ``input``, not more Enters.'
                        ),
                    },
                    'offset': {
                        'type': 'integer',
                        'minimum': 0,
                        'description': (
                            "For action='read' with mode='delta': byte offset (use ``next_offset`` "
                            'from the previous terminal result). If omitted, the server uses '
                            'the last read/input cursor for that session.'
                        ),
                    },
                    'mode': {
                        'type': 'string',
                        'enum': ['delta', 'snapshot'],
                        'description': (
                            "For action='read': 'delta' returns only new bytes since ``offset`` "
                            '(or since the server cursor if ``offset`` is omitted); '
                            "'snapshot' returns the current full buffer view."
                        ),
                    },
                },
                'required': ['action'],
                'allOf': [
                    {
                        'if': {'properties': {'action': {'const': 'open'}}},
                        'then': {'required': ['command']},
                    },
                    {
                        'if': {'properties': {'action': {'const': 'input'}}},
                        'then': {'required': ['session_id']},
                    },
                    {
                        'if': {'properties': {'action': {'const': 'read'}}},
                        'then': {'required': ['session_id']},
                    },
                ],
            },
        },
    }


def _opt_int(v: object) -> int | None:
    if v is None or v == '':
        return None
    if not isinstance(v, (int, str, bytes, bytearray)):
        msg = f'Expected an integer-compatible value, got {type(v).__name__}'
        raise TypeError(msg)
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

        submit = arguments.get('submit', True)
        if isinstance(submit, str):
            submit = submit.strip().lower() not in ('false', '0', 'no')

        return TerminalInputAction(
            session_id=session_id,
            input=str(input_val),
            is_control=is_control,
            control=str(control_val) if control_val is not None else None,
            submit=bool(submit),
            rows=rows,
            cols=cols,
        )

    elif action == 'read':
        session_id = arguments.get('session_id')
        if not session_id:
            raise ValueError("Terminal 'read' action requires 'session_id'")
        mode = str(arguments.get('mode', 'delta') or 'delta').lower()
        if mode not in {'delta', 'snapshot'}:
            raise ValueError("Terminal 'read' action requires mode in {'delta','snapshot'}")
        return TerminalReadAction(
            session_id=session_id,
            offset=_opt_int(arguments.get('offset')),
            mode=mode,
            rows=_opt_int(arguments.get('rows')),
            cols=_opt_int(arguments.get('cols')),
        )

    raise ValueError(f'Unknown terminal manager action: {action}')
