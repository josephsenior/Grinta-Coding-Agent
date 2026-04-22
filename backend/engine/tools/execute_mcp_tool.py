"""MCP Gateway Tool — single proxy for all MCP tool calls.

Instead of injecting 50+ individual MCP tool schemas into the LLM context,
we expose ONE gateway tool. The model sees MCP tool names/descriptions in
the system prompt and routes calls through this gateway.
"""

EXECUTE_MCP_TOOL_TOOL_NAME = 'call_mcp_tool'


def create_execute_mcp_tool_tool() -> dict:
    """Create the MCP gateway tool definition."""
    return {
        'type': 'function',
        'function': {
            'name': EXECUTE_MCP_TOOL_TOOL_NAME,
            'description': (
                'Call any external MCP tool by name. '
                'See the <MCP_TOOLS> section for names and descriptions. '
                'Put **every** tool-specific parameter inside the ``arguments`` object '
                'using the exact keys from that tool schema (camelCase as given). '
                'Do not place parameter keys at the top level next to ``tool_name`` — '
                'that yields empty args and MCP validation errors (-32602). '
                'Context7 example: '
                '``{"tool_name":"resolve-library-id","arguments":{"libraryName":"React","query":"useEffect cleanup"}}`` '
                'then '
                '``{"tool_name":"query-docs","arguments":{"libraryId":"/facebook/react","query":"useEffect patterns"}}``.'
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
                            'Required. Object of argument names to values exactly as the MCP tool schema defines '
                            '(e.g. Context7 resolve-library-id needs both libraryName and query; '
                            'query-docs needs libraryId and query).'
                        ),
                    },
                },
                'required': ['tool_name', 'arguments'],
            },
        },
    }
