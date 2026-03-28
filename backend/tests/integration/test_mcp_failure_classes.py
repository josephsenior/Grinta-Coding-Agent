"""Integration-style tests for MCP failure-class envelopes and retry behavior."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.ledger.action.mcp import MCPAction
from backend.gateway.integrations.mcp.mcp_utils import call_tool_mcp


class FakeMcpError(Exception):
    """Local stand-in for MCP validation failures in tests."""


@pytest.mark.asyncio
async def test_mcp_validation_error_envelope() -> None:
    action = MCPAction(name="search-web", arguments={"queries": ["ai news"]})

    client = AsyncMock()
    client.tools = [SimpleNamespace(name="search-web")]
    client.tool_map = {
        "search-web": SimpleNamespace(
            inputSchema={
                "type": "object",
                "properties": {
                    "queries": {"type": "string"},
                },
            }
        )
    }
    client.exposed_to_protocol = {}
    client.call_tool = AsyncMock(side_effect=FakeMcpError("MCP error -32602: invalid_type"))

    with patch("backend.gateway.integrations.mcp.mcp_utils.McpError", FakeMcpError):
        obs = await call_tool_mcp([client], action)

    payload = json.loads(obs.content)
    assert payload["ok"] is False
    assert payload["error_code"] == "MCP_TOOL_VALIDATION_ERROR"
    assert payload["retryable"] is True


@pytest.mark.asyncio
async def test_mcp_timeout_error_envelope() -> None:
    action = MCPAction(name="search-web", arguments={"queries": "ai news"})

    client = AsyncMock()
    client.tools = [SimpleNamespace(name="search-web")]
    client.exposed_to_protocol = {}
    client.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

    obs = await call_tool_mcp([client], action)

    payload = json.loads(obs.content)
    assert payload["ok"] is False
    assert payload["error_code"] == "MCP_TOOL_TIMEOUT"
    assert payload["retryable"] is True


@pytest.mark.asyncio
async def test_mcp_unavailable_tool_error_envelope() -> None:
    action = MCPAction(name="nonexistent-tool", arguments={})

    client = AsyncMock()
    client.tools = [SimpleNamespace(name="search-web")]
    client.exposed_to_protocol = {}

    obs = await call_tool_mcp([client], action)

    payload = json.loads(obs.content)
    assert payload["ok"] is False
    assert payload["error_code"] == "MCP_TOOL_UNAVAILABLE"
    assert payload["retryable"] is True
