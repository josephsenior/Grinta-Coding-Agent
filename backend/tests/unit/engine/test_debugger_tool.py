"""Tests for generic debugger tool argument mapping."""

from __future__ import annotations

import pytest

from backend.engine.tools.debugger import (
    DEBUGGER_TOOL_NAME,
    create_debugger_tool,
    handle_debugger_tool,
)
from backend.ledger.action.debugger import DebuggerAction


def _assert_debugger_attrs(action: DebuggerAction, expected: dict[str, object]) -> None:
    for attr, value in expected.items():
        assert getattr(action, attr) == value


def test_create_debugger_tool_is_generic() -> None:
    tool = create_debugger_tool()
    assert tool['function']['name'] == DEBUGGER_TOOL_NAME
    assert 'DAP-over-TCP' in tool['function']['description']
    properties = tool['function']['parameters']['properties']
    assert 'adapter_command' in properties
    assert 'adapter_transport' in properties
    assert 'adapter_host' in properties
    assert 'adapter_port' in properties
    assert 'launch_config' in properties
    assert '{port}' in properties['adapter_command']['description']
    all_of = tool['function']['parameters']['allOf']
    session_rules = [
        rule
        for rule in all_of
        if rule.get('then', {}).get('required') == ['session_id']
    ]
    assert session_rules
    set_breakpoint_rules = [
        rule
        for rule in all_of
        if rule.get('then', {}).get('required') == ['session_id', 'file']
    ]
    assert set_breakpoint_rules


def test_start_maps_generic_dap_args() -> None:
    act = handle_debugger_tool(
        {
            'action': 'start',
            'adapter': 'node',
            'adapter_id': 'pwa-node',
            'adapter_command': ['node', 'adapter.js'],
            'adapter_transport': 'tcp',
            'adapter_host': '127.0.0.1',
            'adapter_port': '12345',
            'request': 'launch',
            'launch_config': {'type': 'pwa-node', 'program': 'server.js'},
            'initialize_options': {'client': 'test'},
            'args': ['--x', 1],
            'breakpoints': [{'file': 'server.js', 'line': 5}],
            'stop_on_entry': 'true',
            'timeout': '20',
        }
    )
    assert isinstance(act, DebuggerAction)
    _assert_debugger_attrs(
        act,
        {
            'debug_action': 'start',
            'adapter': 'node',
            'adapter_id': 'pwa-node',
            'adapter_command': ['node', 'adapter.js'],
            'adapter_transport': 'tcp',
            'adapter_host': '127.0.0.1',
            'adapter_port': 12345,
            'launch_config': {'type': 'pwa-node', 'program': 'server.js'},
            'initialize_options': {'client': 'test'},
            'args': ['--x', '1'],
            'breakpoints': [{'file': 'server.js', 'line': 5}],
            'stop_on_entry': True,
            'timeout': 20.0,
        },
    )


def test_status_maps_session() -> None:
    act = handle_debugger_tool({'action': 'status', 'session_id': 'dbg-1'})
    assert act.debug_action == 'status'
    assert act.session_id == 'dbg-1'


def test_rejects_missing_action() -> None:
    with pytest.raises(ValueError, match='action'):
        handle_debugger_tool({})
