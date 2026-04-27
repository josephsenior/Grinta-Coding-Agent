"""Tests for python_debugger tool argument mapping."""

from __future__ import annotations

import pytest

from backend.engine.tools.python_debugger import handle_python_debugger_tool
from backend.ledger.action.debugger import DebuggerAction


def test_start_maps_debugger_args() -> None:
    act = handle_python_debugger_tool(
        {
            'action': 'start',
            'program': 'app.py',
            'args': ['--x', 1],
            'breakpoints': [{'file': 'app.py', 'line': 5}],
            'stop_on_entry': 'true',
            'timeout': '20',
        }
    )
    assert isinstance(act, DebuggerAction)
    assert act.debug_action == 'start'
    assert act.program == 'app.py'
    assert act.args == ['--x', '1']
    assert act.breakpoints == [{'file': 'app.py', 'line': 5}]
    assert act.stop_on_entry is True
    assert act.timeout == 20.0


def test_status_maps_session() -> None:
    act = handle_python_debugger_tool({'action': 'status', 'session_id': 'dbg-1'})
    assert act.debug_action == 'status'
    assert act.session_id == 'dbg-1'


def test_rejects_missing_action() -> None:
    with pytest.raises(ValueError, match='action'):
        handle_python_debugger_tool({})
