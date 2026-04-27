"""Tests for generic debugger tool argument mapping."""

from __future__ import annotations

import pytest

from backend.engine.tools.debugger import (
    DEBUGGER_TOOL_NAME,
    create_debugger_tool,
    handle_debugger_tool,
    handle_python_debugger_tool,
)
from backend.ledger.action.debugger import DebuggerAction


def test_create_debugger_tool_is_generic() -> None:
    tool = create_debugger_tool()
    assert tool['function']['name'] == DEBUGGER_TOOL_NAME
    properties = tool['function']['parameters']['properties']
    assert 'adapter_command' in properties
    assert 'launch_config' in properties


def test_start_maps_generic_dap_args() -> None:
    act = handle_debugger_tool(
        {
            'action': 'start',
            'adapter': 'node',
            'adapter_id': 'pwa-node',
            'adapter_command': ['node', 'adapter.js'],
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
    assert act.debug_action == 'start'
    assert act.adapter == 'node'
    assert act.adapter_id == 'pwa-node'
    assert act.adapter_command == ['node', 'adapter.js']
    assert act.launch_config == {'type': 'pwa-node', 'program': 'server.js'}
    assert act.initialize_options == {'client': 'test'}
    assert act.args == ['--x', '1']
    assert act.breakpoints == [{'file': 'server.js', 'line': 5}]
    assert act.stop_on_entry is True
    assert act.timeout == 20.0


def test_python_debugger_alias_sets_python_adapter() -> None:
    act = handle_python_debugger_tool({'action': 'start', 'program': 'app.py'})
    assert act.debug_action == 'start'
    assert act.adapter == 'python'
    assert act.program == 'app.py'


def test_status_maps_session() -> None:
    act = handle_debugger_tool({'action': 'status', 'session_id': 'dbg-1'})
    assert act.debug_action == 'status'
    assert act.session_id == 'dbg-1'


def test_rejects_missing_action() -> None:
    with pytest.raises(ValueError, match='action'):
        handle_debugger_tool({})
