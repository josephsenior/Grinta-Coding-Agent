from typing import Any

from backend.core.errors import FunctionCallValidationError
from backend.core.tools.tool_names import TERMINAL_MANAGER_TOOL_NAME
from backend.engine.function_calling.helpers import (
    set_security_risk,
    validate_security_risk,
)
from backend.ledger.action.terminal import (
    TerminalCloseAction,
    TerminalInputAction,
    TerminalListAction,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
)


def create_terminal_manager_tool() -> dict[str, Any]:
    return {
        'type': 'function',
        'function': {
            'name': TERMINAL_MANAGER_TOOL_NAME,
            'description': (
                'Manage interactive PTY terminals and background shell sessions.\n\n'
                '**When to use `terminal_manager` vs `execute_bash` / `execute_powershell`**\n'
                '* Shell executor — one-shot build/test/install/git commands.\n'
                '* `terminal_manager` — REPLs, ssh, interactive prompts, background '
                'session polling, waiting for server readiness, listing/stopping sessions.\n\n'
                '**Actions**\n'
                '* `open` — start an interactive PTY session and run the first command.\n'
                '* `read` / `logs` — fetch output (`mode=delta` preferred; remember `next_offset`).\n'
                '* `wait` — block until output matches `pattern` or `timeout` expires '
                '(ideal for "server ready" gates).\n'
                '* `list` — show active background/interactive sessions.\n'
                '* `input` — send follow-up commands to the SAME session.\n'
                '* `close` / `stop` — release a session immediately.\n\n'
                'Background sessions created by `is_background=true` use ids like '
                '`bg-XXXXXXXX`. Poll them with `read`, `logs`, or `wait` — not `open` again.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'open',
                            'input',
                            'read',
                            'logs',
                            'wait',
                            'list',
                            'close',
                            'stop',
                        ],
                        'description': (
                            "'open': start session and run ``command`` once. "
                            "'read'/'logs': fetch output (delta=new since cursor). "
                            "'wait': block until ``pattern`` matches or ``timeout`` expires. "
                            "'list': show active sessions. "
                            "'input': send more text/control to the same session. "
                            "'close'/'stop': release the session immediately."
                        ),
                    },
                    'session_id': {
                        'type': 'string',
                        'description': (
                            'Session id from `open`, `is_background=true`, or idle detach '
                            '(e.g. `bg-a1b2c3d4`). Required for input/read/logs/wait/close/stop.'
                        ),
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
                            "For action='read'/'logs' with mode='delta': byte offset "
                            '(use ``next_offset`` from the previous terminal result). '
                            'If omitted, the server uses the last read/input cursor.'
                        ),
                    },
                    'mode': {
                        'type': 'string',
                        'enum': ['delta', 'snapshot'],
                        'description': (
                            "For action='read'/'logs': 'delta' returns only new bytes since "
                            '``offset`` (or since the server cursor if omitted); '
                            "'snapshot' returns the current full buffer view."
                        ),
                    },
                    'pattern': {
                        'type': 'string',
                        'description': (
                            "For action='wait': case-insensitive regex matched against "
                            'accumulated session output (e.g. `listening on|Compiled|ready`).'
                        ),
                    },
                    'timeout': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': 600,
                        'description': (
                            "For action='wait': seconds to wait for ``pattern`` before "
                            'returning a timeout result. Default 30.'
                        ),
                    },
                    'security_risk': {
                        'type': 'string',
                        'enum': ['LOW', 'MEDIUM', 'HIGH'],
                        'description': (
                            "Required when action='open'. Classify the risk of the command "
                            'you are launching.'
                        ),
                    },
                },
                'required': ['action'],
                'allOf': [
                    {
                        'if': {'properties': {'action': {'const': 'open'}}},
                        'then': {'required': ['command', 'security_risk']},
                    },
                    {
                        'if': {
                            'properties': {
                                'action': {
                                    'enum': [
                                        'input',
                                        'read',
                                        'logs',
                                        'wait',
                                        'close',
                                        'stop',
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


def _opt_int(v: object) -> int | None:
    if v is None or v == '':
        return None
    if not isinstance(v, (int, str, bytes, bytearray)):
        msg = f'Expected an integer-compatible value, got {type(v).__name__}'
        raise TypeError(msg)
    return int(v)


def _validate_action(arguments: dict) -> str:
    action = arguments.get('action')
    if not action:
        raise FunctionCallValidationError(
            "terminal_manager requires an 'action' "
            '(open, input, read, logs, wait, list, close, or stop).'
        )
    valid = ('open', 'input', 'read', 'logs', 'wait', 'list', 'close', 'stop')
    if action not in valid:
        raise FunctionCallValidationError(
            f'Unknown action: {action!r}. Use one of: {", ".join(valid)}.'
        )
    return action


def _handle_open_action(arguments: dict) -> TerminalRunAction:
    cmd = arguments.get('command')
    if not cmd:
        raise ValueError("Terminal 'open' action requires 'command'")
    validate_security_risk(arguments, TERMINAL_MANAGER_TOOL_NAME)
    action = TerminalRunAction(
        command=cmd,
        cwd=arguments.get('cwd'),
        rows=_opt_int(arguments.get('rows')),
        cols=_opt_int(arguments.get('cols')),
    )
    set_security_risk(action, arguments)
    return action


def _has_input_content(
    input_val: object, control_val: object, rows: int | None
) -> bool:
    if str(input_val).strip():
        return True
    if control_val and str(control_val).strip():
        return True
    return rows is not None


def _validate_input_params(
    session_id: object, input_val: object, control_val: object, rows: int | None
) -> None:
    if not session_id:
        raise ValueError(
            "Terminal 'input' requires 'session_id'. Use action='open' first."
        )
    if not _has_input_content(input_val, control_val, rows):
        raise ValueError(
            "Terminal 'input' action requires 'input' and/or 'control' and/or "
            "'rows' + 'cols'"
        )


def _coerce_is_control(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() == 'true'
    return bool(value)


def _coerce_submit(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ('false', '0', 'no')
    return bool(value)


def _handle_input_action(arguments: dict) -> TerminalInputAction:
    session_id = arguments.get('session_id')
    input_val = arguments.get('input', '') or ''
    control_val = arguments.get('control')
    rows = _opt_int(arguments.get('rows'))
    cols = _opt_int(arguments.get('cols'))
    _validate_input_params(session_id, input_val, control_val, rows)
    if not isinstance(session_id, str):
        raise ValueError("Terminal 'input' action requires a string 'session_id'.")
    is_control = _coerce_is_control(arguments.get('is_control', False))
    submit = _coerce_submit(arguments.get('submit', True))
    return TerminalInputAction(
        session_id=session_id,
        input=str(input_val),
        is_control=is_control,
        control=str(control_val) if control_val is not None else None,
        submit=submit,
        rows=rows,
        cols=cols,
    )


def _handle_read_action(arguments: dict) -> TerminalReadAction:
    session_id = arguments.get('session_id')
    if not session_id:
        raise ValueError(
            "Terminal 'read' requires 'session_id'. Use action='open' first."
        )
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


def _handle_wait_action(arguments: dict) -> TerminalWaitAction:
    session_id = arguments.get('session_id')
    if not session_id or not isinstance(session_id, str):
        raise ValueError("Terminal 'wait' requires a string 'session_id'.")
    pattern = arguments.get('pattern')
    if not pattern or not str(pattern).strip():
        raise ValueError("Terminal 'wait' requires a non-empty 'pattern' regex.")
    timeout = _opt_int(arguments.get('timeout'))
    return TerminalWaitAction(
        session_id=session_id,
        pattern=str(pattern),
        timeout=timeout if timeout is not None else 30,
    )


def _handle_close_action(arguments: dict) -> TerminalCloseAction:
    session_id = arguments.get('session_id')
    if not session_id or not isinstance(session_id, str):
        raise ValueError(
            "Terminal 'close' requires a string 'session_id'. "
            "Use action='open' first to obtain one."
        )
    return TerminalCloseAction(session_id=session_id)


def handle_terminal_manager_tool(arguments: dict) -> Any:
    """Route terminal manager intents back into the core backend actions."""
    action = _validate_action(arguments)
    if action == 'open':
        return _handle_open_action(arguments)
    if action == 'input':
        return _handle_input_action(arguments)
    if action in ('close', 'stop'):
        return _handle_close_action(arguments)
    if action == 'list':
        return TerminalListAction()
    if action == 'wait':
        return _handle_wait_action(arguments)
    if action == 'logs':
        logs_args = dict(arguments)
        logs_args['action'] = 'read'
        logs_args.setdefault('mode', 'delta')
        return _handle_read_action(logs_args)
    return _handle_read_action(arguments)
