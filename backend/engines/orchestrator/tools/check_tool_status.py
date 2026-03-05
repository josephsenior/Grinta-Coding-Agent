"""Tool for checking the status of available tools and MCP servers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.engines.orchestrator.contracts import ChatCompletionToolParam


def _extract_tool_names(mcp_tools: dict[str, Any] | list[dict[str, Any]] | None) -> list[str]:
    """Extract MCP tool names from supported container shapes."""
    if not mcp_tools:
        return []

    if isinstance(mcp_tools, dict):
        return sorted(str(name) for name in mcp_tools.keys())

    names: list[str] = []
    for tool in mcp_tools:
        try:
            name = tool.get("function", {}).get("name")
            if isinstance(name, str) and name:
                names.append(name)
        except Exception:
            continue
    return sorted(set(names))


def _collect_mcp_connection_errors(limit: int = 10) -> list[dict[str, Any]]:
    """Collect recent MCP connection errors for degraded-mode visibility."""
    try:
        from backend.mcp_integration.error_collector import mcp_error_collector

        recent_errors = mcp_error_collector.get_errors()[-limit:]
        return [
            {
                "timestamp": error.timestamp,
                "server": error.server_name,
                "type": error.server_type,
                "message": error.error_message,
            }
            for error in recent_errors
        ]
    except Exception:
        return []

def create_check_tool_status_tool() -> ChatCompletionToolParam:
    """Create the check_tool_status tool."""
    return create_tool_definition(
        name="check_tool_status",
        description="Checks the availability and status of all registered tools and connected MCP servers.",
        properties={
            "tool_name": {
                "type": "string",
                "description": "Optional: Check status for a specific tool name. If omitted, checks all tools.",
            }
        },
        required=[],
    )

def build_check_tool_status_action(arguments: dict[str, Any], mcp_tools: dict[str, Any]) -> Any:
    """Run the health check for tools."""
    from backend.events.action import AgentThinkAction

    tool_name = arguments.get("tool_name")
    checked_at = datetime.now(UTC).isoformat()

    available_tools = _extract_tool_names(mcp_tools)
    errors = _collect_mcp_connection_errors()
    degraded = bool(errors)

    if tool_name:
        normalized_tool_name = str(tool_name)
        tool_known = normalized_tool_name in available_tools
        tools_payload = [
            {
                "name": normalized_tool_name,
                "status": "ready" if tool_known else "not_found",
                "scope": "mcp",
            }
        ]
    else:
        tools_payload = [
            {"name": name, "status": "ready", "scope": "mcp"}
            for name in available_tools
        ]

    payload = {
        "checked_at": checked_at,
        "scope": "mcp_tools",
        "degraded": degraded,
        "summary": {
            "available_tool_count": len(available_tools),
            "error_count": len(errors),
        },
        "tools": tools_payload,
        "recent_connection_errors": errors,
    }

    human_lines = [
        f"Tool health checked at {checked_at}.",
        f"MCP tools available: {len(available_tools)}.",
    ]
    if tool_name:
        status_text = (
            "READY" if tools_payload and tools_payload[0]["status"] == "ready" else "NOT FOUND"
        )
        human_lines.append(f"Requested tool '{tool_name}': {status_text}.")
    if degraded:
        human_lines.append(
            f"MCP is in DEGRADED mode ({len(errors)} recent connection error(s)); prefer fail-soft fallbacks."
        )

    structured = json.dumps(payload, ensure_ascii=False)
    return AgentThinkAction(thought="\n".join(human_lines + [f"[TOOL_STATUS] {structured}"]))
