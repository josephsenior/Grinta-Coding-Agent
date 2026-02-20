"""Convenience exports for Forge's Model Context Protocol client utilities."""

from backend.mcp_integration.client import MCPClient
from backend.mcp_integration.error_collector import mcp_error_collector
from backend.mcp_integration.tool import MCPClientTool
from backend.mcp_integration.utils import (
    add_mcp_tools_to_agent,
    call_tool_mcp,
    convert_mcps_to_tools,
    create_mcps,
    fetch_mcp_tools_from_config,
)

__all__ = [
    "MCPClient",
    "MCPClientTool",
    "add_mcp_tools_to_agent",
    "call_tool_mcp",
    "convert_mcps_to_tools",
    "create_mcps",
    "fetch_mcp_tools_from_config",
    "mcp_error_collector",
]
