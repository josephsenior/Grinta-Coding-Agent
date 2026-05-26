"""Tests for backend.engine.function_calling — action handler functions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling import (
    _handle_cmd_run_tool,
    _handle_finish_tool,
    _process_single_tool_call,
    combine_thought,
    set_security_risk,
)
from backend.ledger.action import (
    ActionSecurityRisk,
    CmdRunAction,
    MessageAction,
    PlaybookFinishAction,
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
        from backend.engine.tools.security_utils import RISK_LEVELS

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


# ---------------------------------------------------------------------------
# _handle_finish_tool
# ---------------------------------------------------------------------------


class TestHandleFinishTool:
    """Tests for _handle_finish_tool."""

    def test_agent_finish_accepts_execution_payload(self):
        action = _handle_finish_tool(
            {
                'status': 'completed',
                'summary': 'Task complete',
                'actions_taken': ['Changed the implementation'],
                'verification': {'status': 'passed', 'details': 'pytest passed'},
                'remaining_items': [],
                'next_step': 'Ship it',
            },
            mode='agent',
        )
        assert isinstance(action, PlaybookFinishAction)
        assert action.final_thought == 'Task complete'
        assert action.outputs['actions_taken'] == ['Changed the implementation']

    def test_plan_finish_accepts_plan_payload(self):
        action = _handle_finish_tool(
            {
                'status': 'completed',
                'summary': 'Plan ready',
                'plan': ['Inspect files', 'Make the change', 'Run tests'],
                'assumptions': ['Existing behavior stays stable'],
                'next_step': 'Switch to Agent Mode',
            },
            mode='plan',
        )
        assert isinstance(action, PlaybookFinishAction)
        assert action.final_thought == 'Plan ready'
        assert action.outputs['plan'] == [
            'Inspect files',
            'Make the change',
            'Run tests',
        ]

    def test_plan_finish_rejects_missing_required_fields(self):
        with pytest.raises(FunctionCallValidationError, match='summary'):
            _handle_finish_tool(
                {
                    'status': 'completed',
                    'plan': ['Do it'],
                    'assumptions': [],
                    'next_step': 'Switch to Agent Mode',
                },
                mode='plan',
            )

    def test_plan_finish_blocked_allows_empty_plan(self):
        action = _handle_finish_tool(
            {
                'status': 'blocked',
                'summary': 'Target subsystem is unclear',
                'plan': [],
                'assumptions': [],
                'next_step': 'Clarify the target subsystem',
            },
            mode='plan',
        )
        assert action.outputs['status'] == 'blocked'
        assert action.outputs['plan'] == []

    def test_plan_finish_completed_requires_non_empty_plan(self):
        with pytest.raises(FunctionCallValidationError, match='non-empty plan'):
            _handle_finish_tool(
                {
                    'status': 'completed',
                    'summary': 'Plan ready',
                    'plan': [],
                    'assumptions': [],
                    'next_step': 'Switch to Agent Mode',
                },
                mode='plan',
            )

    def test_agent_finish_rejects_plan_payload(self):
        with pytest.raises(FunctionCallValidationError, match='actions_taken'):
            _handle_finish_tool(
                {
                    'status': 'completed',
                    'summary': 'Plan ready',
                    'plan': ['Do it'],
                    'assumptions': [],
                    'next_step': 'Switch to Agent Mode',
                },
                mode='agent',
            )


class TestModeToolValidation:
    def test_chat_mode_rejects_mutating_tool_call(self):
        tool_call = SimpleNamespace(function=SimpleNamespace(name='create'))

        with pytest.raises(FunctionCallValidationError, match='Chat Mode'):
            _process_single_tool_call(
                tool_call,
                {'type': 'file', 'path': 'demo.txt', 'content': 'x'},
                mode='chat',
            )
