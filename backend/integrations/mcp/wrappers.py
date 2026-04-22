"""Wrapper (synthetic) tools layered atop MCP server tools.

These wrappers avoid extra round trips for common composite or filtered queries
by leveraging the local cache (see cache.py):

  - get_component_cached / get_block_cached: thin wrappers exposing refresh flag

Execution Path:
  call_tool_mcp (utils.py) intercepts names in WRAPPER_TOOL_REGISTRY and dispatches
  directly here, returning an MCPObservation-compatible JSON structure.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _wrap_simple_passthrough(tool_name: str):
    async def _inner(mcps, args: dict[str, Any], call_tool_func) -> dict:
        return await call_tool_func(tool_name, args)

    return _inner


WRAPPER_TOOL_REGISTRY: dict[str, Callable] = {
    'get_component_cached': _wrap_simple_passthrough('get_component'),
    'get_block_cached': _wrap_simple_passthrough('get_block'),
}


def wrapper_tool_params(available_server_tools: list[str]) -> list[dict]:
    """Describe wrapper tool signatures for MCP discovery based on available underlying tools."""
    params: list[dict] = []
    names = set(available_server_tools)
    if 'get_component' in names:
        params.append(
            {
                'type': 'function',
                'function': {
                    'name': 'get_component_cached',
                    'description': 'Retrieve a component definition (uses cache; pass refresh=true to refetch).',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'name': {
                                'type': 'string',
                                'description': 'Exact component name',
                            },
                            'refresh': {
                                'type': 'boolean',
                                'description': 'If true, bypass cache',
                            },
                        },
                        'required': ['name'],
                    },
                },
            },
        )
    if 'get_block' in names:
        params.append(
            {
                'type': 'function',
                'function': {
                    'name': 'get_block_cached',
                    'description': 'Retrieve a block definition (uses cache; pass refresh=true to refetch).',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'name': {
                                'type': 'string',
                                'description': 'Exact block name',
                            },
                            'refresh': {
                                'type': 'boolean',
                                'description': 'If true, bypass cache',
                            },
                        },
                        'required': ['name'],
                    },
                },
            },
        )
    return params
