"""Convenience exports for Grinta's Model Context Protocol client utilities.

Exports are intentionally lazy. Native first-party tools import light MCP leaf
modules during planner construction; importing the entire MCP utility graph at
package import time can create circular imports with wrapper tools.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    'MCPClient',
    'MCPClientTool',
    'get_mcp_bootstrap_status',
    'add_mcp_tools_to_agent',
    'call_tool_mcp',
    'convert_mcps_to_tools',
    'create_mcps',
    'fetch_mcp_tools_from_config',
    'get_mcp_config_bus',
    'mcp_error_collector',
]

_EXPORTS = {
    'MCPClient': ('backend.integrations.mcp.client', 'MCPClient'),
    'MCPClientTool': ('backend.integrations.mcp.tool', 'MCPClientTool'),
    'get_mcp_bootstrap_status': (
        'backend.integrations.mcp.mcp_bootstrap_status',
        'get_mcp_bootstrap_status',
    ),
    'add_mcp_tools_to_agent': (
        'backend.integrations.mcp.mcp_utils',
        'add_mcp_tools_to_agent',
    ),
    'call_tool_mcp': ('backend.integrations.mcp.mcp_utils', 'call_tool_mcp'),
    'convert_mcps_to_tools': (
        'backend.integrations.mcp.mcp_utils',
        'convert_mcps_to_tools',
    ),
    'create_mcps': ('backend.integrations.mcp.mcp_utils', 'create_mcps'),
    'fetch_mcp_tools_from_config': (
        'backend.integrations.mcp.mcp_utils',
        'fetch_mcp_tools_from_config',
    ),
    'get_mcp_config_bus': (
        'backend.integrations.mcp.config_bus',
        'get_mcp_config_bus',
    ),
    'mcp_error_collector': (
        'backend.integrations.mcp.error_collector',
        'mcp_error_collector',
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
