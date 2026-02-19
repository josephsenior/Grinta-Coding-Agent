"""Tests for orchestrator tool factory functions — finish, think, task_tracker, condensation_request."""

from __future__ import annotations

from backend.engines.orchestrator.tools.finish import create_finish_tool
from backend.engines.orchestrator.tools.think import create_think_tool
from backend.engines.orchestrator.tools.task_tracker import create_task_tracker_tool
from backend.engines.orchestrator.tools.condensation_request import (
    create_condensation_request_tool,
)
from backend.llm.tool_names import FINISH_TOOL_NAME, TASK_TRACKER_TOOL_NAME


class TestCreateFinishTool:
    def test_type(self):
        tool = create_finish_tool()
        assert tool["type"] == "function"

    def test_name(self):
        tool = create_finish_tool()
        assert tool["function"]["name"] == FINISH_TOOL_NAME

    def test_has_message_param(self):
        tool = create_finish_tool()
        params = tool["function"]["parameters"]
        assert "message" in params["properties"]
        assert "message" in params["required"]

    def test_description_nonempty(self):
        tool = create_finish_tool()
        assert len(tool["function"]["description"]) > 10


class TestCreateThinkTool:
    def test_type(self):
        tool = create_think_tool()
        assert tool["type"] == "function"

    def test_name(self):
        tool = create_think_tool()
        assert tool["function"]["name"] == "think"

    def test_has_thought_param(self):
        tool = create_think_tool()
        params = tool["function"]["parameters"]
        assert "thought" in params["properties"]
        assert "thought" in params["required"]


class TestCreateTaskTrackerTool:
    def test_type(self):
        tool = create_task_tracker_tool()
        assert tool["type"] == "function"

    def test_name(self):
        tool = create_task_tracker_tool()
        assert tool["function"]["name"] == TASK_TRACKER_TOOL_NAME

    def test_has_command_param(self):
        tool = create_task_tracker_tool()
        params = tool["function"]["parameters"]
        assert "command" in params["properties"]
        assert "command" in params["required"]
        assert params["properties"]["command"]["enum"] == ["view", "plan"]

    def test_has_task_list_param(self):
        tool = create_task_tracker_tool()
        params = tool["function"]["parameters"]
        assert "task_list" in params["properties"]
        assert params["properties"]["task_list"]["type"] == "array"


class TestCreateCondensationRequestTool:
    def test_type(self):
        tool = create_condensation_request_tool()
        assert tool["type"] == "function"

    def test_name(self):
        tool = create_condensation_request_tool()
        assert tool["function"]["name"] == "request_condensation"

    def test_no_required_params(self):
        tool = create_condensation_request_tool()
        params = tool["function"]["parameters"]
        assert params["required"] == []
        assert params["properties"] == {}
