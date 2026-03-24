"""Convenience exports for Forge's Model Context Protocol client utilities."""

from backend.mcp_client.client import MCPClient
from backend.mcp_client.error_collector import mcp_error_collector
from backend.mcp_client.mcp_bootstrap_status import get_mcp_bootstrap_status
from backend.mcp_client.tool import MCPClientTool
from backend.mcp_client.utils import (
    add_mcp_tools_to_agent,
    call_tool_mcp,
    convert_mcps_to_tools,
    create_mcps,
    fetch_mcp_tools_from_config,
)

__all__ = [
    "MCPClient",
    "MCPClientTool",
    "get_mcp_bootstrap_status",
    "add_mcp_tools_to_agent",
    "call_tool_mcp",
    "convert_mcps_to_tools",
    "create_mcps",
    "fetch_mcp_tools_from_config",
    "mcp_error_collector",
]
