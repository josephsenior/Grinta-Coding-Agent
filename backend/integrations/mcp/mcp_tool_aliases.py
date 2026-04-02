"""Resolve MCP tool name collisions by exposing stable aliases to the model."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.integrations.mcp.client import MCPClient


def _slugify_segment(name: str, *, fallback: str = 'mcp') -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '_', (name or '').strip()).strip('_').lower()
    return s or fallback


def prepare_mcp_tool_exposed_names(mcps: list[MCPClient], reserved: set[str]) -> None:
    """Rename MCP tools that collide with ``reserved`` or prior MCP tools.

    Updates each client's ``tools``, ``tool_map``, and ``exposed_to_protocol``.
    The wire name sent to the server remains the original (protocol) name.
    """
    from backend.integrations.mcp.tool import MCPClientTool

    used: set[str] = set(reserved)
    for client in mcps:
        srv = _slugify_segment(
            getattr(getattr(client, '_server_config', None), 'name', None) or 'mcp',
            fallback='mcp',
        )
        new_tools: list[MCPClientTool] = []
        new_map: dict[str, MCPClientTool] = {}
        exp_to_proto: dict[str, str] = {}
        for t in list(client.tools):
            protocol_name = t.name
            exposed = protocol_name
            if exposed in used:
                base = f'mcp_{srv}_{_slugify_segment(protocol_name, fallback="tool")}'
                exposed = base
                n = 2
                while exposed in used:
                    exposed = f'{base}_{n}'
                    n += 1
            used.add(exposed)
            nt = MCPClientTool(
                name=exposed,
                description=t.description,
                inputSchema=t.inputSchema,
            )
            new_tools.append(nt)
            new_map[exposed] = nt
            exp_to_proto[exposed] = protocol_name
        client.tools = new_tools
        client.tool_map = new_map
        client.exposed_to_protocol = exp_to_proto
        client.register_alias_context(mcps, frozenset(reserved))
