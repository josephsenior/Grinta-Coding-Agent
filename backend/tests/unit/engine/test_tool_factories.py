"""Tests for orchestrator tool factory functions."""

from __future__ import annotations

from backend.core.tools.tool_names import (
    TASK_TRACKER_TOOL_NAME,
)
from backend.engine.tools.meta_cognition import ASK_USER_TOOL_NAME, create_ask_user_tool
from backend.engine.tools.task_tracker import (
    create_task_tracker_tool,
)


class TestCreateAskUserTool:
    def test_type(self):
        tool = create_ask_user_tool()
        assert tool['type'] == 'function'

    def test_name(self):
        tool = create_ask_user_tool()
        assert tool['function']['name'] == ASK_USER_TOOL_NAME

    def test_requires_questions(self):
        tool = create_ask_user_tool()
        params = tool['function']['parameters']
        assert params['required'] == ['questions']
        assert params['properties']['questions']['type'] == 'array'

    def test_description_nonempty(self):
        tool = create_ask_user_tool()
        assert len(tool['function']['description']) > 10


class TestCreateTaskTrackerTool:
    def test_type(self):
        tool = create_task_tracker_tool()
        assert tool['type'] == 'function'

    def test_name(self):
        tool = create_task_tracker_tool()
        assert tool['function']['name'] == TASK_TRACKER_TOOL_NAME

    def test_has_command_param(self):
        tool = create_task_tracker_tool()
        params = tool['function']['parameters']
        assert 'command' in params['properties']
        assert 'command' in params['required']
        assert params['properties']['command']['enum'] == [
            'view',
            'update',
            'update_status',
        ]

    def test_has_task_list_param(self):
        tool = create_task_tracker_tool()
        params = tool['function']['parameters']
        assert 'task_list' in params['properties']
        assert params['properties']['task_list']['type'] == 'array'
