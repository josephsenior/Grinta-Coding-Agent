"""External integration adapters (MCP).

See README.md for scope. MCP entry points:

- ``integrations.mcp.add_mcp_tools_to_agent`` — bootstrap discovery
- ``integrations.mcp.call_tool_mcp`` — runtime execution
"""

from backend.integrations.mcp import add_mcp_tools_to_agent, call_tool_mcp

__all__ = ['add_mcp_tools_to_agent', 'call_tool_mcp']
