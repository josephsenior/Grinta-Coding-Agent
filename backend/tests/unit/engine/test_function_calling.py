"""Tests for backend.engine.function_calling — action handler functions."""

from __future__ import annotations

from typing import Any, cast

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling import (
    _handle_cmd_run_tool,
    _handle_finish_tool,
    _handle_llm_based_file_edit_tool,
    _handle_str_replace_editor_tool,
    combine_thought,
    set_security_risk,
)
from backend.ledger.action import (
    ActionSecurityRisk,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
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
        action = _handle_cmd_run_tool({'command': 'ls -la'})
        assert isinstance(action, CmdRunAction)
        assert action.command == 'ls -la'

    def test_with_is_input(self):
        action = _handle_cmd_run_tool({'command': 'y', 'is_input': 'true'})
        assert action.is_input is True

    def test_is_input_false(self):
        action = _handle_cmd_run_tool({'command': 'ls', 'is_input': 'false'})
        assert action.is_input is False

    def test_with_timeout(self):
        action = _handle_cmd_run_tool({'command': 'sleep 10', 'timeout': '5.0'})
        assert action.timeout == 5.0

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match='command'):
            _handle_cmd_run_tool({})

    def test_invalid_timeout_raises(self):
        with pytest.raises(FunctionCallValidationError, match='Invalid float'):
            _handle_cmd_run_tool({'command': 'ls', 'timeout': 'not_a_number'})


# ---------------------------------------------------------------------------
# _handle_finish_tool
# ---------------------------------------------------------------------------


class TestHandleFinishTool:
    """Tests for _handle_finish_tool."""

    def test_basic_finish(self):
        action = _handle_finish_tool({'message': 'Task complete'})
        assert isinstance(action, PlaybookFinishAction)
        assert action.final_thought == 'Task complete'

    def test_missing_message_raises(self):
        with pytest.raises(FunctionCallValidationError, match='message'):
            _handle_finish_tool({})


# ---------------------------------------------------------------------------
# _handle_llm_based_file_edit_tool
# ---------------------------------------------------------------------------


class TestHandleLlmBasedFileEditTool:
    """Tests for _handle_llm_based_file_edit_tool."""

    def test_basic_edit(self):
        action = _handle_llm_based_file_edit_tool(
            {
                'path': '/workspace/app.py',
                'content': "print('hello')",
            }
        )
        assert isinstance(action, FileEditAction)
        assert action.path == '/workspace/app.py'
        assert action.content == "print('hello')"

    def test_with_range(self):
        action = _handle_llm_based_file_edit_tool(
            {
                'path': '/workspace/app.py',
                'content': 'new line',
                'start': 5,
                'end': 10,
            }
        )
        assert action.start == 5
        assert action.end == 10

    def test_missing_path_raises(self):
        with pytest.raises(FunctionCallValidationError, match='path'):
            _handle_llm_based_file_edit_tool({'content': 'data'})

    def test_missing_content_raises(self):
        with pytest.raises(FunctionCallValidationError, match='content'):
            _handle_llm_based_file_edit_tool({'path': '/workspace/app.py'})


# ---------------------------------------------------------------------------
# _handle_str_replace_editor_tool
# ---------------------------------------------------------------------------


class TestHandleStrReplaceEditorTool:
    """Tests for _handle_str_replace_editor_tool."""

    def test_view_returns_file_read(self):
        action = _handle_str_replace_editor_tool(
            {
                'command': 'view_file',
                'path': '/workspace/app.py',
                'security_risk': 'low',
            }
        )
        assert isinstance(action, FileReadAction)
        assert action.path == '/workspace/app.py'

    def test_view_with_range(self):
        action = _handle_str_replace_editor_tool(
            {
                'command': 'view_file',
                'path': '/workspace/app.py',
                'view_range': [10, 20],
                'security_risk': 'low',
            }
        )
        assert isinstance(action, FileReadAction)
        assert action.view_range == [10, 20]

    def test_str_replace_returns_file_edit(self):
        action = _handle_str_replace_editor_tool(
            {
                'command': 'replace_text',
                'path': '/workspace/app.py',
                'old_str': 'x = 1',
                'new_str': 'x = 2',
                'security_risk': 'low',
            }
        )
        assert isinstance(action, FileEditAction)
        assert action.path == '/workspace/app.py'

    def test_create_returns_file_edit(self):
        action = _handle_str_replace_editor_tool(
            {
                'command': 'create_file',
                'path': '/workspace/new.py',
                'file_text': '# new file',
                'security_risk': 'low',
            }
        )
        assert isinstance(action, FileEditAction)

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match='command'):
            _handle_str_replace_editor_tool({'path': '/workspace/app.py'})

    def test_missing_path_raises(self):
        with pytest.raises(FunctionCallValidationError, match='path'):
            _handle_str_replace_editor_tool({'command': 'view_file'})

    def test_invalid_argument_raises(self):
        with pytest.raises(FunctionCallValidationError, match='Unexpected'):
            _handle_str_replace_editor_tool(
                {
                    'command': 'replace_text',
                    'path': '/workspace/app.py',
                    'invalid_arg': 'bad',
                    'security_risk': 'low',
                }
            )
