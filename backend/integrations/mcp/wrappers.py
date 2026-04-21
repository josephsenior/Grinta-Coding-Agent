"""Wrapper (synthetic) tools layered atop MCP server tools.

These wrappers avoid extra round trips for common composite or filtered queries
by leveraging the local cache (see cache.py):

  - search_components: fuzzy / substring search over cached component list
  - get_component_cached / get_block_cached: thin wrappers exposing refresh flag

Execution Path:
  call_tool_mcp (utils.py) intercepts names in WRAPPER_TOOL_REGISTRY and dispatches
  directly here, returning an MCPObservation-compatible JSON structure.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from .cache import get_cached

REQUIRED_UNDERLYING = {
    'list_components': ['search_components'],
    'get_component': ['get_component_cached'],
    'get_block': ['get_block_cached'],
}


def _fuzzy_score(needle: str, hay: str) -> float:
    needle_l, hay_l = (needle.lower(), hay.lower())
    if needle_l == hay_l:
        return 1.0
    if needle_l in hay_l:
        return 0.6 + 0.4 * (len(needle_l) / len(hay_l))
    it = iter(hay_l)
    matched = sum(any(c == ch for ch in it) for c in needle_l)
    return matched / len(needle_l)


def _wrap_simple_passthrough(tool_name: str):
    async def _inner(mcps, args: dict[str, Any], call_tool_func) -> dict:
        return await call_tool_func(tool_name, args)

    return _inner


async def _get_components_list(call_tool_func) -> list[str]:
    """Get list of components from cache or by calling list_components tool."""
    cached = get_cached('list_components', {})
    if not cached:
        result = await call_tool_func('list_components', {})
        cached = result

    components: list[str] = []
    if isinstance(cached, dict):
        for seg in cached.get('content', []):
            if isinstance(seg, dict) and seg.get('type') == 'text':
                text = seg.get('text', '')
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        components = parsed
                        break
                except Exception:
                    continue
    return components


def _score_and_filter_components(
    components: Sequence[Any], query: str, fuzzy: bool
) -> list[tuple[float, str]]:
    """Score components based on query and filter by threshold."""
    query_l = query.lower()
    scored: list[tuple[float, str]] = []

    for name in components:
        if not isinstance(name, str):
            continue

        if fuzzy:
            score = _fuzzy_score(query_l, name)
            if score < 0.15:
                continue
        elif query_l in name.lower():
            score = 1.0
        else:
            continue

        scored.append((score, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


async def search_components(mcps, args: dict[str, Any], call_tool_func) -> dict:
    """Return ranked list of component names matching query using local cache and fuzzy scoring."""
    query = args.get('query')
    if not query:
        return {
            'content': [
                {
                    'type': 'text',
                    'text': json.dumps({'error': 'query parameter required'}),
                }
            ]
        }

    limit = int(args.get('limit', 10))
    fuzzy = bool(args.get('fuzzy', True))

    # Get components list
    components = await _get_components_list(call_tool_func)

    # Score and filter
    scored = _score_and_filter_components(components, query, fuzzy)

    # Build response
    top = [n for _, n in scored[:limit]]
    payload = {'query': query, 'results': top, 'total_matches': len(scored)}
    return {
        'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}]
    }



WRAPPER_TOOL_REGISTRY: dict[str, Callable] = {
    'search_components': search_components,
    'get_component_cached': _wrap_simple_passthrough('get_component'),
    'get_block_cached': _wrap_simple_passthrough('get_block'),
}


def wrapper_tool_params(available_server_tools: list[str]) -> list[dict]:
    """Describe wrapper tool signatures for MCP discovery based on available underlying tools."""
    params: list[dict] = []
    names = set(available_server_tools)
    if 'list_components' in names:
        params.append(
            {
                'type': 'function',
                'function': {
                    'name': 'search_components',
                    'description': 'Fuzzy search over component names (cached locally) to narrow down before fetching full component data.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {
                                'type': 'string',
                                'description': 'Search string (substring or fuzzy).',
                            },
                            'limit': {
                                'type': 'integer',
                                'description': 'Max results to return (default 10).',
                            },
                            'fuzzy': {
                                'type': 'boolean',
                                'description': 'Enable fuzzy subsequence matching (default true).',
                            },
                        },
                        'required': ['query'],
                    },
                },
            },
        )
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
