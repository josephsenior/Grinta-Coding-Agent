"""MCP Gateway Tool — single proxy for all MCP tool calls.

Instead of injecting 50+ individual MCP tool schemas into the LLM context,
we expose ONE gateway tool. The model sees MCP tool names/descriptions in
the system prompt and routes calls through this gateway.
"""

MCP_GATEWAY_TOOL_NAME = "call_mcp_tool"


def create_mcp_gateway_tool() -> dict:
    """Create the MCP gateway tool definition."""
    return {
        "type": "function",
        "function": {
            "name": MCP_GATEWAY_TOOL_NAME,
            "description": (
                "Call any external MCP tool by name. "
                "See the <MCP_TOOLS> section in your instructions for available tool names and descriptions. "
                "Pass the tool name and its arguments as a JSON object."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "The exact name of the MCP tool to call (from the <MCP_TOOLS> list).",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments to pass to the MCP tool as key-value pairs.",
                    },
                },
                "required": ["tool_name"],
            },
        },
    }
