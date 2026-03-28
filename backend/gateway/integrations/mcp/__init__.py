"""Convenience exports for Forge's Model Context Protocol client utilities."""

from backend.gateway.integrations.mcp.client import MCPClient
from backend.gateway.integrations.mcp.error_collector import mcp_error_collector
from backend.gateway.integrations.mcp.mcp_bootstrap_status import get_mcp_bootstrap_status
from backend.gateway.integrations.mcp.tool import MCPClientTool
from backend.gateway.integrations.mcp.mcp_utils import (
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
