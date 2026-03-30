from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.core.logger import app_logger as logger


def _extract_tool_names(tools: Iterable[dict[str, Any]] | None) -> set[str]:
    if not tools:
        return set()

    names: set[str] = set()
    for tool in tools:
        try:
            fn = tool.get("function", {})
            name = fn.get("name")
            if isinstance(name, str) and name:
                names.add(name)
        except Exception:
            continue
    return names


def validate_internal_toolset(
    tools: Iterable[dict[str, Any]] | None,
    *,
    strict: bool = True,
) -> list[str]:
    """Validate that all exposed internal tools have dispatch handlers.

    Returns a sorted list of missing tool names.

    strict=True raises RuntimeError to fail fast in production/dev.
    """

    from backend.engine.function_calling import _create_tool_dispatch_map

    exposed = _extract_tool_names(tools)
    dispatchable = set(_create_tool_dispatch_map().keys())

    missing = sorted(exposed - dispatchable)
    if missing:
        msg = (
            "Tool registry mismatch: planner exposed tool(s) without dispatch handler(s): "
            + ", ".join(missing)
        )
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)

    return missing


def validate_mcp_tool_name_collisions(
    internal_tools: Iterable[dict[str, Any]] | None,
    mcp_tool_names: Iterable[str] | None,
    *,
    strict: bool = False,
) -> list[str]:
    """Detect collisions between internal tool names and MCP tool names.

    Collisions are ambiguous for the model: the same tool name may refer to an
    internal handler or an MCP tool. App currently resolves collisions by
    preferring the internal tool handler.

    Returns a sorted list of colliding names.
    """

    internal = _extract_tool_names(internal_tools)
    mcp = {str(n) for n in (mcp_tool_names or []) if str(n)}

    collisions = sorted(internal & mcp)
    if collisions:
        msg = (
            "MCP tool name collision(s) with internal tools: "
            + ", ".join(collisions)
            + ". Internal tool handlers will take precedence; consider renaming the MCP tool(s)."
        )
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)

    return collisions
