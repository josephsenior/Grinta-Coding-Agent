"""Tests for backend.engines.orchestrator.tools.task_tracker and condensation_request."""
from __future__ import annotations

from backend.engines.orchestrator.tools.task_tracker import (
    _TASK_TRACKER_DESCRIPTION,
    create_task_tracker_tool,
)
from backend.engines.orchestrator.tools.condensation_request import (
    _CONDENSATION_REQUEST_DESCRIPTION,
    create_condensation_request_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _func(tool: dict) -> dict:
    return tool["function"]


def _params(tool: dict) -> dict:
    return _func(tool)["parameters"]


def _props(tool: dict) -> dict:
    return _params(tool).get("properties", {})


def _required(tool: dict) -> list[str]:
    return _params(tool).get("required", [])


# ---------------------------------------------------------------------------
# create_task_tracker_tool
# ---------------------------------------------------------------------------


class TestCreateTaskTrackerTool:
    def setup_method(self):
        self.tool = create_task_tracker_tool()

    def test_returns_dict(self):
        assert isinstance(self.tool, dict)

    def test_type_is_function(self):
        assert self.tool.get("type") == "function"

    def test_name_matches_constant(self):
        from backend.llm.tool_names import TASK_TRACKER_TOOL_NAME
        assert _func(self.tool)["name"] == TASK_TRACKER_TOOL_NAME

    def test_description_set(self):
        desc = _func(self.tool).get("description", "")
        assert len(desc) > 10

    def test_description_matches_constant(self):
        assert _func(self.tool)["description"] == _TASK_TRACKER_DESCRIPTION

    def test_command_is_required(self):
        assert "command" in _required(self.tool)

    def test_command_has_enum(self):
        props = _props(self.tool)
        assert "command" in props
        enum = props["command"].get("enum", [])
        assert "view" in enum
        assert "update" in enum

    def test_task_list_property_exists(self):
        props = _props(self.tool)
        assert "task_list" in props

    def test_task_list_is_array(self):
        task_list = _props(self.tool)["task_list"]
        assert task_list["type"] == "array"

    def test_task_list_items_have_required_fields(self):
        task_list = _props(self.tool)["task_list"]
        items = task_list.get("items", {})
        required_item_fields = items.get("required", [])
        assert "id" in required_item_fields
        assert "description" in required_item_fields
        assert "status" in required_item_fields

    def test_task_status_enum(self):
        task_list = _props(self.tool)["task_list"]
        items = task_list.get("items", {})
        status_prop = items.get("properties", {}).get("status", {})
        status_enum = status_prop.get("enum", [])
        assert "pending" in status_enum
        assert "in_progress" in status_enum
        assert "completed" in status_enum

    def test_task_list_not_in_required(self):
        # task_list is optional (only required for plan command)
        assert "task_list" not in _required(self.tool)

    def test_command_type_is_string(self):
        props = _props(self.tool)
        assert props["command"]["type"] == "string"


# ---------------------------------------------------------------------------
# _TASK_TRACKER_DESCRIPTION constant
# ---------------------------------------------------------------------------


class TestTaskTrackerDescriptionConstant:
    def test_is_string(self):
        assert isinstance(_TASK_TRACKER_DESCRIPTION, str)

    def test_mentions_view_and_plan(self):
        desc = _TASK_TRACKER_DESCRIPTION
        assert "view" in desc
        assert "plan" in desc.lower() or "plan" in desc


# ---------------------------------------------------------------------------
# create_condensation_request_tool
# ---------------------------------------------------------------------------


class TestCreateCondensationRequestTool:
    def setup_method(self):
        self.tool = create_condensation_request_tool()

    def test_returns_dict(self):
        assert isinstance(self.tool, dict)

    def test_type_is_function(self):
        assert self.tool.get("type") == "function"

    def test_name_is_request_condensation(self):
        assert _func(self.tool)["name"] == "request_condensation"

    def test_description_set(self):
        desc = _func(self.tool).get("description", "")
        assert len(desc) > 10

    def test_description_matches_constant(self):
        assert _func(self.tool)["description"] == _CONDENSATION_REQUEST_DESCRIPTION

    def test_no_required_parameters(self):
        assert _required(self.tool) == []

    def test_no_properties(self):
        assert _props(self.tool) == {}

    def test_params_type_is_object(self):
        assert _params(self.tool)["type"] == "object"


# ---------------------------------------------------------------------------
# _CONDENSATION_REQUEST_DESCRIPTION constant
# ---------------------------------------------------------------------------


class TestCondensationRequestDescriptionConstant:
    def test_is_string(self):
        assert isinstance(_CONDENSATION_REQUEST_DESCRIPTION, str)

    def test_mentions_condensation(self):
        assert "condensa" in _CONDENSATION_REQUEST_DESCRIPTION.lower()
