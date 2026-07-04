"""Tests for ``terminal_manager`` tool argument mapping."""

from __future__ import annotations

import pytest

from backend.core.enums import ActionSecurityRisk
from backend.core.errors import FunctionCallValidationError
from backend.engine.tools.terminal_manager import handle_terminal_manager_tool
from backend.ledger.action.terminal import (
    TerminalCloseAction,
    TerminalInputAction,
    TerminalListAction,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
)


def test_open_maps_rows_and_cols() -> None:
    act = handle_terminal_manager_tool(
        {
            'action': 'open',
            'command': 'echo hi',
            'cwd': '/tmp',
            'rows': 30,
            'cols': 120,
            'security_risk': 'LOW',
        }
    )
    assert isinstance(act, TerminalRunAction)
    assert act.command == 'echo hi'
    assert act.cwd == '/tmp'
    assert act.rows == 30
    assert act.cols == 120
    assert act.security_risk == ActionSecurityRisk.LOW


def test_open_preserves_declared_security_risk() -> None:
    act = handle_terminal_manager_tool(
        {'action': 'open', 'command': 'echo hi', 'security_risk': 'HIGH'}
    )

    assert isinstance(act, TerminalRunAction)
    assert act.security_risk == ActionSecurityRisk.HIGH


def test_input_maps_control_and_resize() -> None:
    act = handle_terminal_manager_tool(
        {
            'action': 'input',
            'session_id': 's1',
            'control': 'C-c',
            'input': 'y',
            'rows': 24,
            'cols': 80,
        }
    )
    assert isinstance(act, TerminalInputAction)
    assert act.session_id == 's1'
    assert act.control == 'C-c'
    assert act.input == 'y'
    assert act.rows == 24
    assert act.cols == 80


def test_input_allows_control_only() -> None:
    act = handle_terminal_manager_tool(
        {
            'action': 'input',
            'session_id': 's2',
            'control': 'esc',
        }
    )
    assert isinstance(act, TerminalInputAction)
    assert act.control == 'esc'
    assert act.input == ''


def test_read_maps_resize() -> None:
    act = handle_terminal_manager_tool(
        {
            'action': 'read',
            'session_id': 's3',
            'rows': 40,
            'cols': 100,
        }
    )
    assert isinstance(act, TerminalReadAction)
    assert act.session_id == 's3'
    assert act.rows == 40
    assert act.cols == 100


def test_close_maps_session_id() -> None:
    act = handle_terminal_manager_tool({'action': 'close', 'session_id': 's4'})
    assert isinstance(act, TerminalCloseAction)
    assert act.session_id == 's4'


def test_close_does_not_require_security_risk() -> None:
    # Close is bookkeeping only — no security_risk gating. The JSON-schema
    # allOf should not require it (and the model must not have to lie about
    # a risk level for an idempotent cleanup call).
    act = handle_terminal_manager_tool({'action': 'close', 'session_id': 's-no-risk'})
    assert isinstance(act, TerminalCloseAction)
    assert act.session_id == 's-no-risk'


def test_close_rejects_missing_session_id() -> None:
    with pytest.raises(ValueError, match='close.*session_id'):
        handle_terminal_manager_tool({'action': 'close'})


def test_close_rejects_non_string_session_id() -> None:
    with pytest.raises(ValueError, match='close.*session_id'):
        handle_terminal_manager_tool({'action': 'close', 'session_id': 123})


def test_wait_maps_pattern_and_timeout() -> None:
    act = handle_terminal_manager_tool(
        {
            'action': 'wait',
            'session_id': 'bg-abc12345',
            'pattern': 'listening on|ready',
            'timeout': 45,
        }
    )
    assert isinstance(act, TerminalWaitAction)
    assert act.session_id == 'bg-abc12345'
    assert act.pattern == 'listening on|ready'
    assert act.timeout == 45


def test_list_maps_to_terminal_list_action() -> None:
    act = handle_terminal_manager_tool({'action': 'list'})
    assert isinstance(act, TerminalListAction)


def test_logs_aliases_read_delta() -> None:
    act = handle_terminal_manager_tool({'action': 'logs', 'session_id': 'bg-deadbeef'})
    assert isinstance(act, TerminalReadAction)
    assert act.session_id == 'bg-deadbeef'
    assert act.mode == 'delta'


def test_stop_aliases_close() -> None:
    act = handle_terminal_manager_tool({'action': 'stop', 'session_id': 'bg-12345678'})
    assert isinstance(act, TerminalCloseAction)
    assert act.session_id == 'bg-12345678'


def test_input_rejects_empty_operation() -> None:
    with pytest.raises(ValueError, match='input.*control'):
        handle_terminal_manager_tool(
            {
                'action': 'input',
                'session_id': 'x',
            }
        )


class TestActionValidation:
    """Missing / unrecognised action values raise FunctionCallValidationError."""

    def test_missing_action_raises(self) -> None:
        with pytest.raises(FunctionCallValidationError, match="requires an 'action'"):
            handle_terminal_manager_tool({'command': 'dir'})

    def test_none_action_raises(self) -> None:
        with pytest.raises(FunctionCallValidationError, match="requires an 'action'"):
            handle_terminal_manager_tool({'action': None})

    def test_unknown_action_launch_raises(self) -> None:
        # Regression: model hallucinated action='launch' — must not crash the step.
        with pytest.raises(
            FunctionCallValidationError, match=r"Unknown action: 'launch'"
        ):
            handle_terminal_manager_tool({'action': 'launch', 'command': 'echo hi'})

    def test_unknown_action_message_contains_valid_actions(self) -> None:
        with pytest.raises(
            FunctionCallValidationError,
            match='Use one of: open, input, read, logs, wait',
        ):
            handle_terminal_manager_tool({'action': 'execute'})
