"""Tool definition and argument mapping for Python DAP/debugpy debugging."""

from __future__ import annotations

from typing import Any, cast

from backend.ledger.action.debugger import DebuggerAction

PYTHON_DEBUGGER_TOOL_NAME = 'python_debugger'


def create_python_debugger_tool() -> dict[str, Any]:
    """Return the function-call schema for the Python debugger tool."""
    return {
        'type': 'function',
        'function': {
            'name': PYTHON_DEBUGGER_TOOL_NAME,
            'description': (
                'Structured Python debugger backed by debugpy/DAP. Use it when logs or '
                'tracebacks are not enough: launch a Python file, set breakpoints, step, '
                'inspect stack frames/scopes/variables, evaluate expressions, continue, '
                'pause, status, or stop. It returns JSON-shaped debugger state; prefer it '
                'over parsing pdb text when runtime state matters.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'start',
                            'set_breakpoints',
                            'continue',
                            'next',
                            'step_in',
                            'step_out',
                            'pause',
                            'stack',
                            'scopes',
                            'variables',
                            'evaluate',
                            'status',
                            'stop',
                        ],
                        'description': 'Debugger operation to perform.',
                    },
                    'session_id': {
                        'type': 'string',
                        'description': 'Debug session ID. Optional on start; required after start.',
                    },
                    'program': {
                        'type': 'string',
                        'description': "Python file to launch for action='start'.",
                    },
                    'cwd': {
                        'type': 'string',
                        'description': 'Optional working directory for the debuggee.',
                    },
                    'args': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Command-line args for the debuggee.',
                    },
                    'python': {
                        'type': 'string',
                        'description': 'Optional Python executable to run debugpy.adapter.',
                    },
                    'breakpoints': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'file': {'type': 'string'},
                                'line': {'type': 'integer'},
                                'condition': {'type': 'string'},
                                'hit_condition': {'type': 'string'},
                                'log_message': {'type': 'string'},
                            },
                            'required': ['line'],
                        },
                        'description': (
                            'Breakpoints for start or set_breakpoints. For start, each item '
                            'also needs file. For set_breakpoints, file may be supplied once '
                            'in the top-level file parameter.'
                        ),
                    },
                    'file': {
                        'type': 'string',
                        'description': "Source file for action='set_breakpoints'.",
                    },
                    'lines': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Simple breakpoint lines for set_breakpoints.',
                    },
                    'thread_id': {
                        'type': 'integer',
                        'description': 'DAP thread id for continue/step/pause/stack. Defaults to current stopped thread.',
                    },
                    'frame_id': {
                        'type': 'integer',
                        'description': 'DAP frame id for scopes/evaluate.',
                    },
                    'variables_reference': {
                        'type': 'integer',
                        'description': 'DAP variablesReference for variables.',
                    },
                    'expression': {
                        'type': 'string',
                        'description': 'Expression for evaluate.',
                    },
                    'count': {
                        'type': 'integer',
                        'description': 'Optional variable page size.',
                    },
                    'stop_on_entry': {
                        'type': 'boolean',
                        'description': 'Pause immediately at program entry on start.',
                    },
                    'just_my_code': {
                        'type': 'boolean',
                        'description': 'Pass debugpy justMyCode. Defaults false for fuller agent introspection.',
                    },
                    'timeout': {
                        'type': 'number',
                        'description': 'Optional timeout in seconds for this debugger operation.',
                    },
                },
                'required': ['action'],
                'allOf': [
                    {
                        'if': {'properties': {'action': {'const': 'start'}}},
                        'then': {'required': ['program']},
                    },
                    {
                        'if': {'properties': {'action': {'const': 'scopes'}}},
                        'then': {'required': ['session_id', 'frame_id']},
                    },
                    {
                        'if': {'properties': {'action': {'const': 'variables'}}},
                        'then': {'required': ['session_id', 'variables_reference']},
                    },
                    {
                        'if': {'properties': {'action': {'const': 'evaluate'}}},
                        'then': {'required': ['session_id', 'expression']},
                    },
                ],
            },
        },
    }


def _list_str(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [str(value)]
    return [str(item) for item in cast(list[object], value)]


def _to_int(value: object) -> int:
    return int(cast(Any, value))


def _list_int(value: object) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [_to_int(value)]
    return [_to_int(item) for item in cast(list[object], value)]


def _opt_int(value: object) -> int | None:
    if value is None or value == '':
        return None
    return _to_int(value)


def _opt_float(value: object) -> float | None:
    if value is None or value == '':
        return None
    return float(cast(Any, value))


def _bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def handle_python_debugger_tool(arguments: dict[str, Any]) -> DebuggerAction:
    """Map tool arguments to a DebuggerAction."""
    debug_action = str(arguments.get('action') or '').strip().lower()
    if not debug_action:
        raise ValueError("python_debugger requires 'action'")

    breakpoints_value: object = arguments.get('breakpoints')
    if breakpoints_value is None:
        breakpoints_value = []
    if not isinstance(breakpoints_value, list):
        raise ValueError("python_debugger 'breakpoints' must be an array")
    breakpoints_raw = cast(list[object], breakpoints_value)

    return DebuggerAction(
        debug_action=debug_action,
        session_id=arguments.get('session_id'),
        program=arguments.get('program'),
        cwd=arguments.get('cwd'),
        args=_list_str(arguments.get('args')),
        breakpoints=[
            dict(cast(dict[str, Any], item))
            for item in breakpoints_raw
            if isinstance(item, dict)
        ],
        file=arguments.get('file'),
        lines=_list_int(arguments.get('lines')),
        thread_id=_opt_int(arguments.get('thread_id')),
        frame_id=_opt_int(arguments.get('frame_id')),
        variables_reference=_opt_int(arguments.get('variables_reference')),
        expression=arguments.get('expression'),
        count=_opt_int(arguments.get('count')),
        stop_on_entry=_bool(arguments.get('stop_on_entry')),
        just_my_code=_bool(arguments.get('just_my_code')),
        python=arguments.get('python'),
        timeout=_opt_float(arguments.get('timeout')),
    )

