"""query_toolbox tool — explore available tools including MCP tools."""

from __future__ import annotations

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action.agent import QueryToolboxAction

QUERY_TOOLBOX_TOOL_NAME = "query_toolbox"

_DESCRIPTION = (
    "Search the full registry of available tools (built-in and MCP) by capability or tag. "
    "Use this tool when you need a specific capability but don't see an appropriate tool in your current toolset. "
    "For example, you could search for 'network', 'db', or a specific command name."
)

def create_query_toolbox_tool() -> ChatCompletionToolParam:
    """Create the query_toolbox tool definition."""
    return create_tool_definition(
        name=QUERY_TOOLBOX_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "capability_query": {
                "type": "string",
                "description": "Keywords or capability tags to search for (e.g., 'docker', 'database', 'network').",
            }
        },
        required=["capability_query"],
    )

def build_query_toolbox_action(arguments: dict) -> QueryToolboxAction:
    """Build the action for the query_toolbox tool call."""
    from backend.core.errors import FunctionCallValidationError

    if "capability_query" not in arguments:
        raise FunctionCallValidationError(
            'Missing required argument "capability_query" in tool call query_toolbox'
        )

    return QueryToolboxAction(capability_query=arguments["capability_query"])
