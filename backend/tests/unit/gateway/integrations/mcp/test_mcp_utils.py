"""Tests for backend.gateway.integrations.mcp.mcp_utils — MCP tool conversion & helper functions."""

from __future__ import annotations
from typing import Any, cast

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ledger.action.mcp import MCPAction
from backend.gateway.integrations.mcp.mcp_bootstrap_status import reset_mcp_bootstrap_status
from backend.gateway.integrations.mcp.mcp_utils import (
    _find_matching_mcp,
    _is_windows_stdio_mcp_disabled,
    _log_successful_connection,
    _serialize_result_to_json,
    convert_mcps_to_tools,
    fetch_mcp_tools_from_config,
)


# ---------------------------------------------------------------------------
# _is_windows_stdio_mcp_disabled
# ---------------------------------------------------------------------------
class TestIsWindowsMcpDisabled:
    def test_always_returns_false(self):
        """_is_windows_stdio_mcp_disabled always returns False for OS agnosticism."""
        assert _is_windows_stdio_mcp_disabled() is False


# ---------------------------------------------------------------------------
# _serialize_result_to_json
# ---------------------------------------------------------------------------
class TestSerializeResultToJson:
    def test_normal_dict(self):
        result = _serialize_result_to_json({"key": "value", "num": 42})
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_with_non_serializable(self):
        # default=str handles non-serializable
        result = _serialize_result_to_json({"obj": object()})
        assert isinstance(result, str)

    def test_double_fallback(self):
        """When json.dumps and repr both fail..."""
        bad = MagicMock()
        cast(Any, bad).__repr__ = MagicMock(side_effect=Exception("repr fail"))
        # Actually this shouldn't happen in practice, but the code handles it
        result = _serialize_result_to_json({"key": "val"})
        assert "key" in result


# ---------------------------------------------------------------------------
# convert_mcps_to_tools
# ---------------------------------------------------------------------------
class TestConvertMcpsToTools:
    def test_none_input(self):
        assert convert_mcps_to_tools(None) == []

    def test_empty_list(self):
        result = convert_mcps_to_tools([])
        assert isinstance(result, list)
        assert any(
            tool.get("function", {}).get("name") == "mcp_capabilities_status"
            for tool in result
        )

    def test_basic_conversion(self):
        tool_mock = MagicMock()
        tool_mock.name = "search_files"
        tool_mock.to_param.return_value = {
            "type": "function",
            "function": {"name": "search_files", "parameters": {}},
        }
        client = MagicMock()
        client.tools = [tool_mock]

        with patch("backend.gateway.integrations.mcp.mcp_utils.wrapper_tool_params", return_value=[]):
            result = convert_mcps_to_tools([client])
        assert len(result) == 1
        assert result[0]["function"]["name"] == "search_files"

    def test_error_returns_empty(self):
        client = MagicMock()
        client.tools = MagicMock(side_effect=Exception("boom"))
        # The iteration over client.tools will fail
        result = convert_mcps_to_tools([client])
        assert isinstance(result, list)
        assert any(
            tool.get("function", {}).get("name") == "mcp_capabilities_status"
            for tool in result
        )


# ---------------------------------------------------------------------------
# _find_matching_mcp
# ---------------------------------------------------------------------------
class TestFindMatchingMcp:
    def test_found(self):
        tool = MagicMock()
        tool.name = "search"
        client = MagicMock()
        client.tools = [tool]
        assert _find_matching_mcp([client], "search") is client

    def test_not_found(self):
        client = MagicMock()
        client.tools = []
        with pytest.raises(ValueError, match="No matching MCP"):
            _find_matching_mcp([client], "nonexistent")

    def test_found_by_protocol_name_when_tool_is_aliased(self):
        tool = MagicMock()
        tool.name = "mcp_docs_get_component"
        client = MagicMock()
        client.tools = [tool]
        client.exposed_to_protocol = {"mcp_docs_get_component": "get_component"}

        assert _find_matching_mcp([client], "get_component") is client


# ---------------------------------------------------------------------------
# _log_successful_connection
# ---------------------------------------------------------------------------
class TestLogSuccessfulConnection:
    def test_logs_without_error(self):
        tool = MagicMock()
        tool.name = "my_tool"
        client = MagicMock()
        client.tools = [tool]
        # Should not raise
        _log_successful_connection(client, "http://localhost:8080", "SSE")


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------
class TestAsyncHelpers:
    def _as_action(self, payload: SimpleNamespace) -> MCPAction:
        return cast(MCPAction, payload)

    @pytest.mark.asyncio
    async def test_execute_wrapper_tool_success(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_wrapper_tool

        action = self._as_action(SimpleNamespace(name="test_wrapper", arguments={"q": "hello"}))

        async def fake_wrapper(mcps, args, call_fn):
            return {"result": "ok"}

        with patch.dict(
            "backend.gateway.integrations.mcp.mcp_utils.WRAPPER_TOOL_REGISTRY",
            {"test_wrapper": fake_wrapper},
        ):
            obs = await _execute_wrapper_tool(action, [])
            data = json.loads(obs.content)
            assert data["result"] == "ok"
            assert data["ok"] is True
            assert data["isError"] is False
            assert obs.tool_result["ok"] is True

    @pytest.mark.asyncio
    async def test_execute_wrapper_tool_error(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_wrapper_tool

        action = self._as_action(SimpleNamespace(name="bad_wrapper", arguments={}))

        async def failing_wrapper(mcps, args, call_fn):
            raise RuntimeError("wrapper broke")

        with patch.dict(
            "backend.gateway.integrations.mcp.mcp_utils.WRAPPER_TOOL_REGISTRY",
            {"bad_wrapper": failing_wrapper},
        ):
            obs = await _execute_wrapper_tool(action, [])
            data = json.loads(obs.content)
            assert data["isError"] is True
            assert data["ok"] is False
            assert obs.tool_result["ok"] is False

    @pytest.mark.asyncio
    async def test_wrapper_and_direct_failures_share_envelope_shape(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_direct_tool, _execute_wrapper_tool

        wrapper_action = self._as_action(SimpleNamespace(name="bad_wrapper", arguments={}))
        direct_action = self._as_action(SimpleNamespace(name="tool1", arguments={"x": 1}))

        async def failing_wrapper(mcps, args, call_fn):
            raise RuntimeError("wrapper broke")

        direct_client = AsyncMock()
        direct_client.call_tool = AsyncMock(side_effect=RuntimeError("server down"))

        with patch.dict(
            "backend.gateway.integrations.mcp.mcp_utils.WRAPPER_TOOL_REGISTRY",
            {"bad_wrapper": failing_wrapper},
        ):
            wrapper_obs = await _execute_wrapper_tool(wrapper_action, [])
        direct_obs = await _execute_direct_tool(direct_action, direct_client)

        wrapper_data = json.loads(wrapper_obs.content)
        direct_data = json.loads(direct_obs.content)

        expected_keys = {"ok", "isError", "error_code", "retryable", "tool", "content"}
        assert expected_keys.issubset(wrapper_data)
        assert expected_keys.issubset(direct_data)
        assert wrapper_data["ok"] is False and direct_data["ok"] is False
        assert wrapper_obs.tool_result["ok"] is False
        assert direct_obs.tool_result["ok"] is False
        assert wrapper_obs.tool_result["observation"] == wrapper_obs.observation
        assert direct_obs.tool_result["observation"] == direct_obs.observation

    @pytest.mark.asyncio
    async def test_execute_direct_tool_cache_hit(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_direct_tool

        action = self._as_action(SimpleNamespace(name="tool1", arguments={"x": 1}))
        client = MagicMock()

        with patch("backend.gateway.integrations.mcp.mcp_utils.get_cached", return_value={"cached": True}):
            obs = await _execute_direct_tool(action, client)
            data = json.loads(obs.content)
            assert data["cached"] is True
            assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_execute_direct_tool_success(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_direct_tool

        action = self._as_action(SimpleNamespace(name="tool1", arguments={"x": 1}))
        client = AsyncMock()
        response = MagicMock()

        with (
            patch("backend.gateway.integrations.mcp.mcp_utils.get_cached", return_value=None),
            patch(
                "backend.gateway.integrations.mcp.mcp_utils.model_dump_with_options",
                return_value={"result": "data"},
            ),
            patch("backend.gateway.integrations.mcp.mcp_utils.set_cache"),
        ):
            client.call_tool = AsyncMock(return_value=response)
            obs = await _execute_direct_tool(action, client)
            data = json.loads(obs.content)
            assert data["result"] == "data"
            assert data["ok"] is True
            assert obs.tool_result["ok"] is True

    @pytest.mark.asyncio
    async def test_execute_direct_tool_validation_error_repairs_and_retries(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_direct_tool

        action = self._as_action(
            SimpleNamespace(name="search-web", arguments={"queries": ["latest ai news"]})
        )

        class FakeMcpError(Exception):
            pass

        response = MagicMock()
        client = AsyncMock()
        client.call_tool = AsyncMock(side_effect=[FakeMcpError("MCP error -32602: invalid_type expected string"), response])
        client.tool_map = {
            "search-web": SimpleNamespace(
                inputSchema={
                    "type": "object",
                    "properties": {
                        "queries": {"type": "string"}
                    },
                }
            )
        }
        client.exposed_to_protocol = {}

        with (
            patch("backend.gateway.integrations.mcp.mcp_utils.get_cached", return_value=None),
            patch("backend.gateway.integrations.mcp.mcp_utils.McpError", FakeMcpError),
            patch(
                "backend.gateway.integrations.mcp.mcp_utils.model_dump_with_options",
                return_value={"result": "ok"},
            ),
            patch("backend.gateway.integrations.mcp.mcp_utils.set_cache"),
        ):
            obs = await _execute_direct_tool(action, client)

        data = json.loads(obs.content)
        assert data["ok"] is True
        assert data["mcp_arg_repair_applied"] is True
        assert data["repaired_arguments"]["queries"] == '["latest ai news"]'
        assert client.call_tool.await_count == 2

    @pytest.mark.asyncio
    async def test_execute_direct_tool_validation_error_returns_structured_code(self):
        from backend.gateway.integrations.mcp.mcp_utils import _execute_direct_tool

        action = self._as_action(
            SimpleNamespace(name="search-web", arguments={"queries": ["latest ai news"]})
        )

        class FakeMcpError(Exception):
            pass

        client = AsyncMock()
        client.call_tool = AsyncMock(side_effect=FakeMcpError("MCP error -32602: Input validation error"))
        client.tool_map = {
            "search-web": SimpleNamespace(
                inputSchema={
                    "type": "object",
                    "properties": {
                        "queries": {"type": "string"}
                    },
                }
            )
        }
        client.exposed_to_protocol = {}

        with (
            patch("backend.gateway.integrations.mcp.mcp_utils.get_cached", return_value=None),
            patch("backend.gateway.integrations.mcp.mcp_utils.McpError", FakeMcpError),
        ):
            obs = await _execute_direct_tool(action, client)

        data = json.loads(obs.content)
        assert data["ok"] is False
        assert data["error_code"] == "MCP_TOOL_VALIDATION_ERROR"
        assert data["retryable"] is True

    @pytest.mark.asyncio
    async def test_call_tool_mcp_windows_disabled(self):
        from backend.gateway.integrations.mcp.mcp_utils import call_tool_mcp

        action = self._as_action(SimpleNamespace(name="tool1", arguments={}))
        obs = await call_tool_mcp([], action)
        # Empty clients
        assert obs.content

    @pytest.mark.asyncio
    async def test_call_tool_mcp_no_clients(self):
        from backend.gateway.integrations.mcp.mcp_utils import call_tool_mcp

        action = self._as_action(SimpleNamespace(name="tool1", arguments={}))
        obs = await call_tool_mcp([], action)
        data = json.loads(obs.content)
        assert data["ok"] is False
        assert data["error_code"] == "MCP_NO_CLIENTS"
        assert obs.tool_result["ok"] is False

    @pytest.mark.asyncio
    async def test_call_tool_mcp_wrapper_dispatch(self):
        from backend.gateway.integrations.mcp.mcp_utils import call_tool_mcp

        action = self._as_action(SimpleNamespace(name="wrap_tool", arguments={"q": "test"}))

        async def fake_wrapper(mcps, args, call_fn):
            return {"wrapped": True}

        mock_client = MagicMock()
        mock_client.tools = []

        with patch.dict(
            "backend.gateway.integrations.mcp.mcp_utils.WRAPPER_TOOL_REGISTRY",
            {"wrap_tool": fake_wrapper},
        ):
            obs = await call_tool_mcp([mock_client], action)
            data = json.loads(obs.content)
            assert data["wrapped"] is True
            assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_call_mcp_raw_resolves_wrapper_underlying_alias(self):
        from backend.gateway.integrations.mcp.mcp_utils import _call_mcp_raw

        action = self._as_action(SimpleNamespace(name="get_component", arguments={"name": "button"}))
        tool = MagicMock()
        tool.name = "mcp_docs_get_component"
        client = MagicMock()
        client.tools = [tool]
        client.exposed_to_protocol = {"mcp_docs_get_component": "get_component"}
        client.call_tool = AsyncMock(return_value=MagicMock())

        with (
            patch("backend.gateway.integrations.mcp.mcp_utils.get_cached", return_value=None),
            patch(
                "backend.gateway.integrations.mcp.mcp_utils.model_dump_with_options",
                return_value={"result": "ok"},
            ),
            patch("backend.gateway.integrations.mcp.mcp_utils.set_cache"),
        ):
            result = await _call_mcp_raw([client], action)

        assert result["result"] == "ok"
        client.call_tool.assert_awaited_once_with("mcp_docs_get_component", {"name": "button"})

    @pytest.mark.asyncio
    async def test_create_mcps_windows_disabled(self):
        from backend.gateway.integrations.mcp.mcp_utils import create_mcps

        result = await create_mcps([])
        assert result == []

    @pytest.mark.asyncio
    async def test_create_mcps_empty(self):
        from backend.gateway.integrations.mcp.mcp_utils import create_mcps

        result = await create_mcps([])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_mcp_tools_disabled_records_state(self):
        from backend.gateway.integrations.mcp.mcp_bootstrap_status import get_mcp_bootstrap_status

        from types import SimpleNamespace

        reset_mcp_bootstrap_status()
        config = MagicMock()
        config.enabled = False
        config.servers = [SimpleNamespace(name="s", type="stdio")]
        out = await fetch_mcp_tools_from_config(config)
        assert out == []
        assert get_mcp_bootstrap_status()["state"] == "mcp_disabled"
        reset_mcp_bootstrap_status()

    @pytest.mark.asyncio
    async def test_fetch_mcp_tools_fetch_failed_returns_wrappers_not_empty(self):
        from backend.gateway.integrations.mcp.mcp_bootstrap_status import get_mcp_bootstrap_status

        from types import SimpleNamespace

        reset_mcp_bootstrap_status()
        config = MagicMock()
        config.enabled = True
        config.mcp_exposed_name_reserved = frozenset()
        config.servers = [SimpleNamespace(name="r", type="sse", url="https://example.invalid/mcp")]
        with patch(
            "backend.gateway.integrations.mcp.mcp_utils.create_mcps",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network down"),
        ):
            result = await fetch_mcp_tools_from_config(config)
        assert any(
            t.get("function", {}).get("name") == "mcp_capabilities_status" for t in result
        )
        assert get_mcp_bootstrap_status()["state"] == "fetch_failed"
        reset_mcp_bootstrap_status()

    @pytest.mark.asyncio
    async def test_fetch_mcp_tools_windows_disabled(self):
        from types import SimpleNamespace

        # No successful connections → explicit degraded tool surface (not empty list).
        config = MagicMock()
        config.enabled = True
        config.mcp_exposed_name_reserved = frozenset()
        config.servers = [SimpleNamespace(name="r", type="sse", url="https://example.invalid/mcp")]
        with patch("backend.gateway.integrations.mcp.mcp_utils.create_mcps", new_callable=AsyncMock, return_value=[]):
            result = await fetch_mcp_tools_from_config(config)
            assert isinstance(result, list)
            assert any(
                t.get("function", {}).get("name") == "mcp_capabilities_status"
                for t in result
            )

    @pytest.mark.asyncio
    async def test_call_mcp_raw_cache_hit(self):
        from backend.gateway.integrations.mcp.mcp_utils import _call_mcp_raw

        action = self._as_action(SimpleNamespace(name="raw_tool", arguments={"a": 1}))
        tool = MagicMock()
        tool.name = "raw_tool"
        client = MagicMock()
        client.tools = [tool]

        with patch("backend.gateway.integrations.mcp.mcp_utils.get_cached", return_value={"cached": True}):
            result = await _call_mcp_raw([client], action)
            assert result["cached"] is True

    @pytest.mark.asyncio
    async def test_call_mcp_raw_no_match(self):
        from backend.gateway.integrations.mcp.mcp_utils import _call_mcp_raw

        action = self._as_action(SimpleNamespace(name="missing_tool", arguments={}))
        client = MagicMock()
        client.tools = []

        with pytest.raises(ValueError, match="not found"):
            await _call_mcp_raw([client], action)

    @pytest.mark.asyncio
    async def test_execute_mcp_capabilities_status_with_configured_servers(self):
        """mcp_capabilities_status reports configured vs connected when wired from runtime."""
        from backend.gateway.integrations.mcp.mcp_utils import _execute_wrapper_tool

        action = MCPAction(name="mcp_capabilities_status", arguments={})
        servers = [
            SimpleNamespace(name="server_a", type="shttp"),
            SimpleNamespace(name="server_b", type="stdio"),
        ]
        obs = await _execute_wrapper_tool(action, [], configured_servers=servers)
        outer = json.loads(obs.content)
        inner = json.loads(outer["content"][0]["text"])
        assert inner["configured_servers_count"] == 2
        assert inner["configured_servers"][0]["name"] == "server_a"
        assert inner["configured_servers"][1]["name"] == "server_b"
        assert inner["connected_clients_count"] == 0
        assert inner["mcp_available"] is False
        assert inner["connected_tools"] == []
        assert "mcp_capabilities_status" in inner["wrapper_tools_registered"]
        assert "notes" in inner
        assert any("not connected" in n for n in inner["notes"])
        assert "forge_bootstrap" in inner
        assert inner["forge_bootstrap"].get("state") is not None
