"""search_available_tools tool — explore available tools including MCP tools."""

from __future__ import annotations

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action.agent import SearchAvailableToolsAction

SEARCH_AVAILABLE_TOOLS_TOOL_NAME = "search_available_tools"

_DESCRIPTION = (
    "Search the full registry of available tools (built-in and MCP) by capability or tag. "
    "Use this tool when you need a specific capability but don't see an appropriate tool in your current toolset. "
    "For example, you could search for 'network', 'db', or a specific command name. "
    "This is not for searching repository text or symbols; use search_code for that."
)

def create_search_available_tools_tool() -> ChatCompletionToolParam:
    """Create the search_available_tools tool definition."""
    return create_tool_definition(
        name=SEARCH_AVAILABLE_TOOLS_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "capability_query": {
                "type": "string",
                "description": "Keywords or capability tags to search for (e.g., 'docker', 'database', 'network').",
            }
        },
        required=["capability_query"],
    )

def build_search_available_tools_action(arguments: dict) -> SearchAvailableToolsAction:
    """Build the action for the search_available_tools tool call."""
    from backend.core.errors import FunctionCallValidationError

    if "capability_query" not in arguments:
        raise FunctionCallValidationError(
            'Missing required argument "capability_query" in tool call search_available_tools'
        )

    return SearchAvailableToolsAction(capability_query=arguments["capability_query"])
