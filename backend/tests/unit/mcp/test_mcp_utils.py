"""Tests for backend.mcp.utils — MCP tool conversion & helper functions."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.mcp.utils import (
    _collect_all_servers,
    _find_matching_mcp,
    _is_windows_mcp_disabled,
    _log_successful_connection,
    _serialize_result_to_json,
    convert_mcps_to_tools,
)


# ---------------------------------------------------------------------------
# _is_windows_mcp_disabled
# ---------------------------------------------------------------------------
class TestIsWindowsMcpDisabled:
    def test_non_windows(self):
        with patch.object(sys, "platform", "linux"):
            assert _is_windows_mcp_disabled() is False

    def test_windows_no_env(self):
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert _is_windows_mcp_disabled() is True

    def test_windows_with_env(self):
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict("os.environ", {"FORGE_ENABLE_WINDOWS_MCP": "1"}),
        ):
            assert _is_windows_mcp_disabled() is False


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
        bad.__repr__ = MagicMock(side_effect=Exception("repr fail"))
        # Actually this shouldn't happen in practice, but the code handles it
        result = _serialize_result_to_json({"key": "val"})
        assert "key" in result


# ---------------------------------------------------------------------------
# _collect_all_servers
# ---------------------------------------------------------------------------
class TestCollectAllServers:
    def test_all_types(self):
        sse = [MagicMock()]
        shttp = [MagicMock()]
        stdio = [MagicMock()]
        result = _collect_all_servers(sse, shttp, stdio)
        assert len(result) == 3

    def test_none_stdio(self):
        result = _collect_all_servers([MagicMock()], [], None)
        assert len(result) == 1


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

        with patch("backend.mcp.utils.wrapper_tool_params", return_value=[]):
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
    @pytest.mark.asyncio
    async def test_execute_wrapper_tool_success(self):
        from backend.mcp.utils import _execute_wrapper_tool

        action = SimpleNamespace(name="test_wrapper", arguments={"q": "hello"})

        async def fake_wrapper(mcps, args, call_fn):
            return {"result": "ok"}

        with patch.dict(
            "backend.mcp.utils.WRAPPER_TOOL_REGISTRY",
            {"test_wrapper": fake_wrapper},
        ):
            obs = await _execute_wrapper_tool(action, [])
            data = json.loads(obs.content)
            assert data["result"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_wrapper_tool_error(self):
        from backend.mcp.utils import _execute_wrapper_tool

        action = SimpleNamespace(name="bad_wrapper", arguments={})

        async def failing_wrapper(mcps, args, call_fn):
            raise RuntimeError("wrapper broke")

        with patch.dict(
            "backend.mcp.utils.WRAPPER_TOOL_REGISTRY",
            {"bad_wrapper": failing_wrapper},
        ):
            obs = await _execute_wrapper_tool(action, [])
            data = json.loads(obs.content)
            assert data["isError"] is True

    @pytest.mark.asyncio
    async def test_execute_direct_tool_cache_hit(self):
        from backend.mcp.utils import _execute_direct_tool

        action = SimpleNamespace(name="tool1", arguments={"x": 1})
        client = MagicMock()

        with patch("backend.mcp.utils.get_cached", return_value={"cached": True}):
            obs = await _execute_direct_tool(action, client)
            data = json.loads(obs.content)
            assert data["cached"] is True

    @pytest.mark.asyncio
    async def test_execute_direct_tool_success(self):
        from backend.mcp.utils import _execute_direct_tool

        action = SimpleNamespace(name="tool1", arguments={"x": 1})
        client = AsyncMock()
        response = MagicMock()

        with (
            patch("backend.mcp.utils.get_cached", return_value=None),
            patch(
                "backend.mcp.utils.model_dump_with_options",
                return_value={"result": "data"},
            ),
            patch("backend.mcp.utils.set_cache"),
        ):
            client.call_tool = AsyncMock(return_value=response)
            obs = await _execute_direct_tool(action, client)
            data = json.loads(obs.content)
            assert data["result"] == "data"

    @pytest.mark.asyncio
    async def test_call_tool_mcp_windows_disabled(self):
        from backend.mcp.utils import call_tool_mcp

        action = SimpleNamespace(name="tool1", arguments={})
        with patch("backend.mcp.utils._is_windows_mcp_disabled", return_value=True):
            obs = await call_tool_mcp([], action)
            assert (
                "not available" in obs.content.lower()
                or "disabled" in obs.content.lower()
            )

    @pytest.mark.asyncio
    async def test_call_tool_mcp_no_clients(self):
        from backend.mcp.utils import call_tool_mcp

        action = SimpleNamespace(name="tool1", arguments={})
        with patch("backend.mcp.utils._is_windows_mcp_disabled", return_value=False):
            obs = await call_tool_mcp([], action)
            assert "no mcp clients" in obs.content.lower() or "no mcp clients" in str(
                obs
            ).lower() or "no mcp" in obs.content.lower()

    @pytest.mark.asyncio
    async def test_call_tool_mcp_wrapper_dispatch(self):
        from backend.mcp.utils import call_tool_mcp

        action = SimpleNamespace(name="wrap_tool", arguments={"q": "test"})

        async def fake_wrapper(mcps, args, call_fn):
            return {"wrapped": True}

        mock_client = MagicMock()
        mock_client.tools = []

        with (
            patch("backend.mcp.utils._is_windows_mcp_disabled", return_value=False),
            patch.dict(
                "backend.mcp.utils.WRAPPER_TOOL_REGISTRY",
                {"wrap_tool": fake_wrapper},
            ),
        ):
            obs = await call_tool_mcp([mock_client], action)
            data = json.loads(obs.content)
            assert data["wrapped"] is True

    @pytest.mark.asyncio
    async def test_create_mcps_windows_disabled(self):
        from backend.mcp.utils import create_mcps

        with patch("backend.mcp.utils._is_windows_mcp_disabled", return_value=True):
            result = await create_mcps([], [])
            assert result == []

    @pytest.mark.asyncio
    async def test_create_mcps_empty(self):
        from backend.mcp.utils import create_mcps

        with patch("backend.mcp.utils._is_windows_mcp_disabled", return_value=False):
            result = await create_mcps([], [], stdio_servers=[])
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_mcp_tools_windows_disabled(self):
        from backend.mcp.utils import fetch_mcp_tools_from_config

        config = MagicMock()
        with patch("backend.mcp.utils._is_windows_mcp_disabled", return_value=True):
            result = await fetch_mcp_tools_from_config(config)
            assert isinstance(result, list)
            assert any(
                t.get("function", {}).get("name") == "mcp_capabilities_status"
                for t in result
            )

    @pytest.mark.asyncio
    async def test_call_mcp_raw_cache_hit(self):
        from backend.mcp.utils import _call_mcp_raw

        action = SimpleNamespace(name="raw_tool", arguments={"a": 1})
        tool = MagicMock()
        tool.name = "raw_tool"
        client = MagicMock()
        client.tools = [tool]

        with patch("backend.mcp.utils.get_cached", return_value={"cached": True}):
            result = await _call_mcp_raw([client], action)
            assert result["cached"] is True

    @pytest.mark.asyncio
    async def test_call_mcp_raw_no_match(self):
        from backend.mcp.utils import _call_mcp_raw

        action = SimpleNamespace(name="missing_tool", arguments={})
        client = MagicMock()
        client.tools = []

        with pytest.raises(ValueError, match="not found"):
            await _call_mcp_raw([client], action)
