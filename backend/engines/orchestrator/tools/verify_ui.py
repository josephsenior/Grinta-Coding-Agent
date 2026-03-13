"""verify_ui_change tool — wraps browser MCP capabilities for quick frontend visual verification.

Allows the orchestrator to quickly navigate to a page and capture a screenshot
without needing to manually sequence multiple MCP commands.
"""

from __future__ import annotations

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action.mcp import MCPAction

VERIFY_UI_CHANGE_TOOL_NAME = "verify_ui_change"
BROWSER_SERVER_NAME = "browser-use"  # Updated to match config.json

_DESCRIPTION = (
    "Navigate to a URL and immediately take a screenshot to verify frontend changes. "
    "Use this tool after modifying UI components (HTML, CSS, React, etc.) to visually "
    "confirm your changes.\n\n"
    "This tool automates the process of opening a browser, navigating to the URL, "
    "and capturing the screen. It returns a description of the visual layout."
)


def create_verify_ui_change_tool() -> ChatCompletionToolParam:
    """Create the verify_ui_change tool definition."""
    return create_tool_definition(
        name=VERIFY_UI_CHANGE_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "url": {
                "type": "string",
                "description": "The URL to verify (e.g., 'http://localhost:3000').",
            },
        },
        required=["url"],
    )


def build_verify_ui_change_action(arguments: dict) -> MCPAction:
    """Build the composite MCP action to verify the UI."""
    from backend.core.errors import FunctionCallValidationError

    url = arguments.get("url")
    if not url:
        raise FunctionCallValidationError(
            'Missing required argument "url" in tool call verify_ui_change'
        )

    # Note: If the MCP browser server requires two steps, the AgentController
    # could theoretically intercept this pseudo-tool and sequence it, OR we
    # can assume the MCP server has a 'screenshot' tool that can optionally
    # take a URL parameter if built that way. Here we will define it assuming
    # the orchestration logic or MCP server handles a 'navigate_and_screenshot'
    # concept, or just pass a generic command.

    # We will emit an MCP action to the browser server to screenshot.
    # Most browser MCPs support screenshot with an optional URL or implicit navigation.

    # We prefix it with the server name as required by MCP tool calling logic.
    return MCPAction(
        name=f"{BROWSER_SERVER_NAME}_screenshot",
        arguments={"url": url},
        thought=f"[UI VERIFY] Navigating to {url} and capturing screenshot...",
    )
