"""Tests for ``terminal_manager`` tool argument mapping."""

from __future__ import annotations

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.tools.terminal_manager import handle_terminal_manager_tool
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)


def test_open_maps_rows_and_cols() -> None:
    act = handle_terminal_manager_tool(
        {
            'action': 'open',
            'command': 'echo hi',
            'cwd': '/tmp',
            'rows': 30,
            'cols': 120,
        }
    )
    assert isinstance(act, TerminalRunAction)
    assert act.command == 'echo hi'
    assert act.cwd == '/tmp'
    assert act.rows == 30
    assert act.cols == 120


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
        with pytest.raises(FunctionCallValidationError, match="Unknown terminal_manager action"):
            handle_terminal_manager_tool({'action': 'launch', 'command': 'echo hi'})

    def test_unknown_action_message_contains_valid_actions(self) -> None:
        with pytest.raises(FunctionCallValidationError, match="'open'.*'input'.*'read'"):
            handle_terminal_manager_tool({'action': 'execute'})
