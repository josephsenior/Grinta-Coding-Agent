"""Tests for backend.engine.function_calling — action handler functions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.core.errors import FunctionCallNotExistsError, FunctionCallValidationError
from backend.engine.function_calling.dispatch import (
    _handle_cmd_run_tool,
    _process_single_tool_call,
    combine_thought,
    set_security_risk,
)
from backend.ledger.action import (
    ActionSecurityRisk,
    CmdRunAction,
    MessageAction,
)

# ---------------------------------------------------------------------------
# combine_thought
# ---------------------------------------------------------------------------


class TestCombineThought:
    """Tests for combine_thought."""

    def test_add_thought_to_action(self):
        action = CmdRunAction(command='ls')
        cast(Any, action).thought = ''
        result = combine_thought(action, 'I should list files')
        assert 'I should list files' in cast(Any, result).thought

    def test_combine_with_existing_thought(self):
        action = CmdRunAction(command='ls')
        cast(Any, action).thought = 'existing thought'
        result = combine_thought(action, 'new thought')
        assert 'new thought' in cast(Any, result).thought
        assert 'existing thought' in cast(Any, result).thought

    def test_empty_thought_no_change(self):
        action = CmdRunAction(command='ls')
        cast(Any, action).thought = 'original'
        result = combine_thought(action, '')
        assert cast(Any, result).thought == 'original'

    def test_action_without_thought_attr(self):
        action = MessageAction(content='hello')
        # Should not raise even if no 'thought' attribute
        result = combine_thought(action, 'some thought')
        assert result is action


# ---------------------------------------------------------------------------
# set_security_risk
# ---------------------------------------------------------------------------


class TestSetSecurityRisk:
    """Tests for set_security_risk."""

    def test_valid_risk_level(self):
        action = CmdRunAction(command='ls')
        from backend.core.constants import RISK_LEVELS

        if RISK_LEVELS:
            level = list(RISK_LEVELS)[0]
            set_security_risk(action, {'security_risk': level})
            assert isinstance(action.security_risk, ActionSecurityRisk)

    def test_invalid_risk_level_ignored(self):
        action = CmdRunAction(command='ls')
        original = action.security_risk
        set_security_risk(action, {'security_risk': 'NONEXISTENT_LEVEL'})
        assert action.security_risk == original

    def test_no_security_risk_in_args(self):
        action = CmdRunAction(command='ls')
        original = action.security_risk
        set_security_risk(action, {'command': 'ls'})
        assert action.security_risk == original


# ---------------------------------------------------------------------------
# _handle_cmd_run_tool
# ---------------------------------------------------------------------------


class TestHandleCmdRunTool:
    """Tests for _handle_cmd_run_tool."""

    def test_basic_command(self):
        action = _handle_cmd_run_tool({'command': 'ls -la', 'security_risk': 'LOW'})
        assert isinstance(action, CmdRunAction)
        assert action.command == 'ls -la'

    def test_with_is_input(self):
        action = _handle_cmd_run_tool(
            {'command': 'y', 'is_input': 'true', 'security_risk': 'LOW'}
        )
        assert action.is_input is True

    def test_is_input_false(self):
        action = _handle_cmd_run_tool(
            {'command': 'ls', 'is_input': 'false', 'security_risk': 'LOW'}
        )
        assert action.is_input is False

    def test_with_timeout(self):
        action = _handle_cmd_run_tool(
            {'command': 'sleep 10', 'timeout': '5.0', 'security_risk': 'LOW'}
        )
        assert action.timeout == 5.0

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match='command'):
            _handle_cmd_run_tool({})

    def test_invalid_timeout_raises(self):
        with pytest.raises(FunctionCallValidationError, match='Invalid float'):
            _handle_cmd_run_tool(
                {'command': 'ls', 'timeout': 'not_a_number', 'security_risk': 'LOW'}
            )

    def test_glued_windows_drive_sets_thought_hint(self):
        action = _handle_cmd_run_tool(
            {
                'command': 'ls -F app/dashboard/ && ls -F componentsC:/Users/x/foo/',
                'security_risk': 'LOW',
            }
        )
        assert isinstance(action, CmdRunAction)
        assert '[SHELL]' in (action.thought or '')

    def test_separated_windows_drive_no_glue_hint(self):
        action = _handle_cmd_run_tool(
            {'command': 'ls -F components/C:/Users/x/foo/', 'security_risk': 'LOW'}
        )
        assert isinstance(action, CmdRunAction)
        assert not (action.thought or '').strip()

    def test_missing_security_risk_raises(self):
        with pytest.raises(FunctionCallValidationError, match='security_risk'):
            _handle_cmd_run_tool({'command': 'ls'})

    def test_invalid_security_risk_raises(self):
        with pytest.raises(FunctionCallValidationError, match='security_risk'):
            _handle_cmd_run_tool({'command': 'ls', 'security_risk': 'CRITICAL'})


class TestModeToolValidation:
    def test_finish_tool_call_is_not_dispatchable(self):
        tool_call = SimpleNamespace(function=SimpleNamespace(name='finish'))

        with pytest.raises(FunctionCallNotExistsError):
            _process_single_tool_call(
                tool_call,
                {'summary': 'Done'},
                mode='agent',
            )

    def test_chat_mode_rejects_mutating_tool_call(self):
        tool_call = SimpleNamespace(function=SimpleNamespace(name='create'))

        with pytest.raises(FunctionCallValidationError, match='Chat Mode'):
            _process_single_tool_call(
                tool_call,
                {'type': 'file', 'path': 'demo.txt', 'content': 'x'},
                mode='chat',
            )

    def test_chat_mode_allows_read_tool_call(self):
        tool_call = SimpleNamespace(function=SimpleNamespace(name='read'))

        action = _process_single_tool_call(
            tool_call,
            {'type': 'file', 'path': 'demo.txt', 'security_risk': 'LOW'},
            mode='chat',
        )

        from backend.ledger.action import FileReadAction

        assert isinstance(action, FileReadAction)
