"""External integration adapters (MCP).

See README.md for scope. Public exports are resolved lazily so importing a
leaf module such as ``backend.integrations.mcp.native_backends`` does not
eagerly import the full MCP utility stack.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ['add_mcp_tools_to_agent', 'call_tool_mcp']

_EXPORTS = {
    'add_mcp_tools_to_agent': (
        'backend.integrations.mcp.mcp_utils',
        'add_mcp_tools_to_agent',
    ),
    'call_tool_mcp': ('backend.integrations.mcp.mcp_utils', 'call_tool_mcp'),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
