"""Tool definition and argument mapping for DAP debugger sessions."""

from __future__ import annotations

from typing import Any, cast

from backend.ledger.action.debugger import DebuggerAction

DEBUGGER_TOOL_NAME = 'debugger'


def create_debugger_tool() -> dict[str, Any]:
    """Return the function-call schema for the generic debugger tool."""
    return {
        'type': 'function',
        'function': {
            'name': DEBUGGER_TOOL_NAME,
            'description': (
                'Structured Debug Adapter Protocol debugger. Use it when logs or '
                'tracebacks are not enough: launch or attach through any DAP adapter, '
                'set breakpoints, step, inspect stack frames/scopes/variables, evaluate '
                'expressions, continue, pause, status, or stop. For Python, adapter="python" '
                'or a .py program uses the built-in debugpy adapter. For other languages, '
                'provide adapter_command and adapter-specific launch_config.'
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
                    'adapter': {
                        'type': 'string',
                        'description': 'DAP adapter preset/name. Built-in preset: python. Other languages should pass adapter_command.',
                    },
                    'adapter_id': {
                        'type': 'string',
                        'description': 'DAP initialize adapterID. Defaults to adapter/language when omitted.',
                    },
                    'language': {
                        'type': 'string',
                        'description': 'Optional source language label used for adapter inference and result metadata.',
                    },
                    'adapter_command': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Command and arguments that start a DAP adapter over stdio, e.g. ["node", "path/to/adapter.js"].',
                    },
                    'request': {
                        'type': 'string',
                        'enum': ['launch', 'attach'],
                        'description': 'DAP start request. Defaults to launch.',
                    },
                    'launch_config': {
                        'type': 'object',
                        'description': 'Adapter-specific DAP launch/attach arguments. Passed through as JSON.',
                    },
                    'initialize_options': {
                        'type': 'object',
                        'description': 'Optional adapter-specific DAP initializationOptions object.',
                    },
                    'program': {
                        'type': 'string',
                        'description': 'Optional program/script path. Merged into launch_config as program.',
                    },
                    'cwd': {
                        'type': 'string',
                        'description': 'Optional debuggee working directory. Merged into launch_config as cwd.',
                    },
                    'args': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Optional debuggee command-line args. Merged into launch_config as args.',
                    },
                    'python': {
                        'type': 'string',
                        'description': 'Optional Python executable for the built-in python/debugpy adapter preset.',
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
                                'hitCondition': {'type': 'string'},
                                'log_message': {'type': 'string'},
                                'logMessage': {'type': 'string'},
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
                        'description': 'Convenience flag merged into launch_config as stopOnEntry when true.',
                    },
                    'just_my_code': {
                        'type': 'boolean',
                        'description': 'Python/debugpy convenience flag. Other adapters should use launch_config.',
                    },
                    'timeout': {
                        'type': 'number',
                        'description': 'Optional timeout in seconds for this debugger operation.',
                    },
                },
                'required': ['action'],
                'allOf': [
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


def _dict_any(value: object, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"debugger '{name}' must be an object")
    return dict(cast(dict[str, Any], value))


def _breakpoints(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    breakpoints_value: object = arguments.get('breakpoints')
    if breakpoints_value is None:
        breakpoints_value = []
    if not isinstance(breakpoints_value, list):
        raise ValueError("debugger 'breakpoints' must be an array")
    return [
        dict(cast(dict[str, Any], item))
        for item in cast(list[object], breakpoints_value)
        if isinstance(item, dict)
    ]


def handle_debugger_tool(arguments: dict[str, Any]) -> DebuggerAction:
    """Map tool arguments to a DebuggerAction."""
    debug_action = str(arguments.get('action') or '').strip().lower()
    if not debug_action:
        raise ValueError("debugger requires 'action'")

    return DebuggerAction(
        debug_action=debug_action,
        session_id=arguments.get('session_id'),
        adapter=arguments.get('adapter'),
        adapter_id=arguments.get('adapter_id'),
        adapter_command=_list_str(arguments.get('adapter_command')),
        language=arguments.get('language'),
        request=str(arguments.get('request') or 'launch').strip().lower(),
        program=arguments.get('program'),
        cwd=arguments.get('cwd'),
        args=_list_str(arguments.get('args')),
        launch_config=_dict_any(arguments.get('launch_config'), name='launch_config'),
        initialize_options=_dict_any(
            arguments.get('initialize_options'), name='initialize_options'
        ),
        breakpoints=_breakpoints(arguments),
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
