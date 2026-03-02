import pytest
from backend.engines.orchestrator.tools.verify_ui import (
    create_verify_ui_change_tool,
    build_verify_ui_change_action,
    VERIFY_UI_CHANGE_TOOL_NAME,
    BROWSER_SERVER_NAME,
)
from backend.events.action.mcp import MCPAction
from backend.core.exceptions import FunctionCallValidationError


def test_create_verify_ui_change_tool():
    """Test that the verify_ui_change tool definition is created correctly."""
    tool_def = create_verify_ui_change_tool()

    assert tool_def["type"] == "function"
    assert tool_def["function"]["name"] == VERIFY_UI_CHANGE_TOOL_NAME
    assert "url" in tool_def["function"]["parameters"]["properties"]
    assert "url" in tool_def["function"]["parameters"]["required"]


def test_build_verify_ui_change_action_success():
    """Test that building the action succeeds with valid arguments."""
    args = {"url": "http://localhost:3000"}
    action = build_verify_ui_change_action(args)

    assert isinstance(action, MCPAction)
    assert action.name == f"{BROWSER_SERVER_NAME}_screenshot"
    assert action.arguments == {"url": "http://localhost:3000"}
    assert "Navigating to http://localhost:3000" in action.thought


def test_build_verify_ui_change_action_missing_url():
    """Test that building the action fails if 'url' is missing."""
    args: dict[str, str] = {}
    with pytest.raises(
        FunctionCallValidationError, match='Missing required argument "url"'
    ):
        build_verify_ui_change_action(args)
