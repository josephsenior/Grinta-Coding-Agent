"""MCP Gateway Tool — single proxy for all MCP tool calls.

Instead of injecting 50+ individual MCP tool schemas into the LLM context,
we expose ONE gateway tool. The model sees MCP tool names/descriptions in
the system prompt and routes calls through this gateway.
"""

from backend.inference.tool_names import CALL_MCP_TOOL_NAME


def create_execute_mcp_tool_tool() -> dict:
    """Create the MCP gateway tool definition."""
    return {
        'type': 'function',
        'function': {
            'name': CALL_MCP_TOOL_NAME,
            'description': (
                'Call any external MCP tool by name. '
                'See the <MCP_TOOLS> section for names and descriptions. '
                'Put **every** tool-specific parameter inside the ``arguments`` object '
                'using the exact keys from that tool schema (camelCase as given). '
                'Do not place parameter keys at the top level next to ``tool_name`` — '
                'that yields empty args and MCP validation errors (-32602). '
                'Use native `docs_resolve` / `docs_query` and `web_search` / `web_fetch` '
                'for bundled capabilities — not this gateway.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'tool_name': {
                        'type': 'string',
                        'description': 'The exact name of the MCP tool to call (from the <MCP_TOOLS> list).',
                    },
                    'arguments': {
                        'type': 'object',
                        'description': (
                            'Required. Object of argument names to values exactly as the MCP tool schema defines.'
                        ),
                    },
                },
                'required': ['tool_name', 'arguments'],
            },
        },
    }
