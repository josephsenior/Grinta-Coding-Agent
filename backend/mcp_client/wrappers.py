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
from .mcp_bootstrap_status import get_mcp_bootstrap_status

REQUIRED_UNDERLYING = {
    "list_components": ["search_components"],
    "get_component": ["get_component_cached"],
    "get_block": ["get_block_cached"],
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
    cached = get_cached("list_components", {})
    if not cached:
        result = await call_tool_func("list_components", {})
        cached = result

    components: list[str] = []
    if isinstance(cached, dict):
        for seg in cached.get("content", []):
            if isinstance(seg, dict) and seg.get("type") == "text":
                text = seg.get("text", "")
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
    query = args.get("query")
    if not query:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": "query parameter required"}),
                }
            ]
        }

    limit = int(args.get("limit", 10))
    fuzzy = bool(args.get("fuzzy", True))

    # Get components list
    components = await _get_components_list(call_tool_func)

    # Score and filter
    scored = _score_and_filter_components(components, query, fuzzy)

    # Build response
    top = [n for _, n in scored[:limit]]
    payload = {"query": query, "results": top, "total_matches": len(scored)}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
    }


def _windows_stdio_mcp_note() -> str | None:
    """Explain stdio MCP policy without importing utils at module load (breaks cycles)."""
    from backend.mcp_client.utils import _is_windows_stdio_mcp_disabled

    if _is_windows_stdio_mcp_disabled():
        return (
            "On Windows, stdio MCP servers are skipped unless the environment variable "
            "FORGE_ENABLE_WINDOWS_MCP is set (HTTP/SSE/SHTTP servers are still attempted)."
        )
    return None


def _connected_client_summary(client: Any) -> dict[str, Any]:
    cfg = getattr(client, "_server_config", None)
    name = (
        getattr(cfg, "name", None)
        or getattr(cfg, "url", None)
        or getattr(cfg, "command", None)
        or "unknown"
    )
    tools = list(getattr(client, "tools", []) or [])
    return {
        "server_name": name,
        "server_type": getattr(cfg, "type", None),
        "remote_tool_count": len(tools),
        "remote_tools": sorted(t.name for t in tools),
    }


async def mcp_capabilities_status(
    mcps,
    args: dict[str, Any],
    call_tool_func,
    *,
    configured_servers: list[Any] | None = None,
) -> dict:
    """Report configured vs connected MCP state, remote tools, and Forge wrapper tools."""
    mcps_list = list(mcps or [])
    configured = configured_servers or []
    configured_summaries = [
        {"name": getattr(s, "name", ""), "type": getattr(s, "type", "")}
        for s in configured
    ]
    remote_names = sorted(
        {
            tool.name
            for client in mcps_list
            for tool in getattr(client, "tools", [])
        }
    )
    notes: list[str] = []
    n_cfg = len(configured_summaries)
    n_conn = len(mcps_list)
    if n_cfg > n_conn:
        notes.append(
            f"{n_cfg - n_conn} configured server(s) were not connected for this session "
            "(connection timeout, bad URL, transport error, or skipped stdio on Windows)."
        )
    if mcps_list and not remote_names:
        notes.append(
            "Connected server(s) returned zero tools from list_tools(). "
            "Forge may still register wrapper tools (see wrapper_tools_registered); "
            "the LLM tool list merges remote tools plus applicable wrappers."
        )

    win = _windows_stdio_mcp_note()
    if win:
        notes.append(win)

    payload: dict[str, Any] = {
        "mcp_available": bool(mcps_list),
        # Backward-compatible keys (counts / flat tool list)
        "connected_servers": n_conn,
        "connected_tools": remote_names,
        # Clearer diagnostics
        "configured_servers_count": n_cfg,
        "configured_servers": configured_summaries,
        "connected_clients_count": n_conn,
        "connected_clients": [_connected_client_summary(c) for c in mcps_list],
        "wrapper_tools_registered": sorted(WRAPPER_TOOL_REGISTRY.keys()),
        # Last Forge MCP bootstrap outcome (disabled vs unavailable vs degraded vs healthy)
        "forge_bootstrap": get_mcp_bootstrap_status(),
    }
    if notes:
        payload["notes"] = notes

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ]
    }


WRAPPER_TOOL_REGISTRY: dict[str, Callable] = {
    "search_components": search_components,
    "get_component_cached": _wrap_simple_passthrough("get_component"),
    "get_block_cached": _wrap_simple_passthrough("get_block"),
    "mcp_capabilities_status": mcp_capabilities_status,
}


def wrapper_tool_params(available_server_tools: list[str]) -> list[dict]:
    """Describe wrapper tool signatures for MCP discovery based on available underlying tools."""
    params = [
        {
            "type": "function",
            "function": {
                "name": "mcp_capabilities_status",
                "description": (
                    "Report MCP diagnostics: configured servers vs connected clients, "
                    "remote tools from list_tools(), and Forge wrapper tools. "
                    "Use when connected_tools is empty but you still see MCP tools in the agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }
    ]
    names = set(available_server_tools)
    if "list_components" in names:
        params.append(
            {
                "type": "function",
                "function": {
                    "name": "search_components",
                    "description": "Fuzzy search over component names (cached locally) to narrow down before fetching full component data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search string (substring or fuzzy).",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max results to return (default 10).",
                            },
                            "fuzzy": {
                                "type": "boolean",
                                "description": "Enable fuzzy subsequence matching (default true).",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
        )
    if "get_component" in names:
        params.append(
            {
                "type": "function",
                "function": {
                    "name": "get_component_cached",
                    "description": "Retrieve a component definition (uses cache; pass refresh=true to refetch).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Exact component name",
                            },
                            "refresh": {
                                "type": "boolean",
                                "description": "If true, bypass cache",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
        )
    if "get_block" in names:
        params.append(
            {
                "type": "function",
                "function": {
                    "name": "get_block_cached",
                    "description": "Retrieve a block definition (uses cache; pass refresh=true to refetch).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Exact block name",
                            },
                            "refresh": {
                                "type": "boolean",
                                "description": "If true, bypass cache",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
        )
    return params
