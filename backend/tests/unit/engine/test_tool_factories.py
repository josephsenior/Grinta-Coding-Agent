"""Tests for orchestrator tool factory functions — finish, think, task_tracker, condensation_request."""

from __future__ import annotations

from backend.engine.tools.condensation_request import (
    create_summarize_context_tool,
)
from backend.engine.tools.finish import create_finish_tool
from backend.engine.tools.task_tracker import create_task_tracker_tool
from backend.engine.tools.think import create_think_tool
from backend.inference.tool_names import FINISH_TOOL_NAME, TASK_TRACKER_TOOL_NAME


class TestCreateFinishTool:
    def test_type(self):
        tool = create_finish_tool()
        assert tool['type'] == 'function'

    def test_name(self):
        tool = create_finish_tool()
        assert tool['function']['name'] == FINISH_TOOL_NAME

    def test_has_message_param(self):
        tool = create_finish_tool()
        params = tool['function']['parameters']
        assert 'message' in params['properties']
        assert 'message' in params['required']

    def test_description_nonempty(self):
        tool = create_finish_tool()
        assert len(tool['function']['description']) > 10


class TestCreateThinkTool:
    def test_type(self):
        tool = create_think_tool()
        assert tool['type'] == 'function'

    def test_name(self):
        tool = create_think_tool()
        assert tool['function']['name'] == 'think'

    def test_has_thought_param(self):
        tool = create_think_tool()
        params = tool['function']['parameters']
        assert 'thought' in params['properties']
        assert 'thought' in params['required']


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
        assert params['properties']['command']['enum'] == ['view', 'update', 'plan']

    def test_has_task_list_param(self):
        tool = create_task_tracker_tool()
        params = tool['function']['parameters']
        assert 'task_list' in params['properties']
        assert params['properties']['task_list']['type'] == 'array'


class TestCreateCondensationRequestTool:
    def test_type(self):
        tool = create_summarize_context_tool()
        assert tool['type'] == 'function'

    def test_name(self):
        tool = create_summarize_context_tool()
        assert tool['function']['name'] == 'summarize_context'

    def test_no_required_params(self):
        tool = create_summarize_context_tool()
        params = tool['function']['parameters']
        assert params['required'] == []
        assert params['properties'] == {}
