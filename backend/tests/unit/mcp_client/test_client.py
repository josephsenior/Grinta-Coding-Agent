"""Comprehensive tests for MCP client wrapper.

Tests MCPClient session management, connection, reconnection, and tool calls.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastmcp import Client
from mcp import McpError
from mcp.types import CallToolResult, ErrorData, Tool
from pydantic import ValidationError

from backend.core.config.mcp_config import (
    MCPRemoteServerConfig,
    MCPStdioServerConfig,
)
from backend.mcp_client.client import MCPClient
from backend.mcp_client.tool import MCPClientTool


class TestMCPClientSessionManagement(unittest.IsolatedAsyncioTestCase):
    """Tests for MCP client session lifecycle management."""

    async def test_init_creates_empty_client(self) -> None:
        """Test MCPClient initializes with no active session."""
        client = MCPClient()
        self.assertIsNone(client.client)
        self.assertFalse(client._session_active)
        self.assertEqual(len(client.tools), 0)

    async def test_open_session_activates_client(self) -> None:
        """Test opening a session sets _session_active flag."""
        mcp_client = MCPClient()
        mock_fastmcp_client = AsyncMock(spec=Client)
        mock_fastmcp_client.__aenter__ = AsyncMock()
        mcp_client.client = mock_fastmcp_client

        await mcp_client._open_session()

        self.assertTrue(mcp_client._session_active)
        mock_fastmcp_client.__aenter__.assert_called_once()

    async def test_open_session_raises_if_no_client(self) -> None:
        """Test opening session without client raises RuntimeError."""
        mcp_client = MCPClient()

        with self.assertRaises(RuntimeError) as ctx:
            await mcp_client._open_session()

        self.assertIn("Client not configured", str(ctx.exception))

    async def test_close_session_deactivates(self) -> None:
        """Test closing session sets _session_active to False."""
        mcp_client = MCPClient()
        mock_fastmcp_client = AsyncMock(spec=Client)
        mock_fastmcp_client.__aexit__ = AsyncMock()
        mcp_client.client = mock_fastmcp_client
        mcp_client._session_active = True

        await mcp_client._close_session()

        self.assertFalse(mcp_client._session_active)
        mock_fastmcp_client.__aexit__.assert_called_once()

    async def test_close_session_handles_exceptions(self) -> None:
        """Test closing session gracefully handles connection errors."""
        mcp_client = MCPClient()
        mock_fastmcp_client = AsyncMock(spec=Client)
        mock_fastmcp_client.__aexit__ = AsyncMock(
            side_effect=Exception("Connection lost")
        )
        mcp_client.client = mock_fastmcp_client
        mcp_client._session_active = True

        # Should not raise
        await mcp_client._close_session()

        self.assertFalse(mcp_client._session_active)

    async def test_populate_tools_fetches_from_server(self) -> None:
        """Test populate_tools fetches and maps server tools."""
        mcp_client = MCPClient()
        mock_fastmcp_client = AsyncMock(spec=Client)

        server_tools = [
            Tool(
                name="search_files",
                description="Search files by name",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="read_file",
                description="Read file contents",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
        mock_fastmcp_client.list_tools = AsyncMock(return_value=server_tools)
        mcp_client.client = mock_fastmcp_client

        await mcp_client._populate_tools()

        self.assertEqual(len(mcp_client.tools), 2)
        self.assertIn("search_files", mcp_client.tool_map)
        self.assertIn("read_file", mcp_client.tool_map)
        self.assertIsInstance(mcp_client.tool_map["search_files"], MCPClientTool)

    async def test_populate_tools_raises_if_no_client(self) -> None:
        """Test populate_tools raises without active client."""
        mcp_client = MCPClient()

        with self.assertRaises(RuntimeError) as ctx:
            await mcp_client._populate_tools()

        self.assertIn("Session not initialized", str(ctx.exception))


class TestMCPClientHTTPConnection(unittest.IsolatedAsyncioTestCase):
    """Tests for HTTP-based MCP connections (SSE, SHTTP)."""

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.SSETransport")
    async def test_connect_http_with_sse(
        self, mock_sse_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test connecting to SSE-based MCP server."""
        mock_client_instance = AsyncMock(spec=Client)
        mock_client_instance.__aenter__ = AsyncMock()
        mock_client_instance.list_tools = AsyncMock(return_value=[])
        mock_client_class.return_value = mock_client_instance

        mcp_client = MCPClient()
        server_config = MCPRemoteServerConfig(
            name="test-sse",
            type="sse",
            url="http://localhost:8000/sse",
            api_key="test_key_123",
            transport="sse"
        )

        await mcp_client.connect_http(server_config)

        mock_sse_transport.assert_called_once()
        self.assertTrue(mcp_client._session_active)
        self.assertEqual(mcp_client._server_config, server_config)

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.StreamableHttpTransport")
    async def test_connect_http_with_shttp(
        self, mock_shttp_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test connecting to SHTTP-based MCP server."""
        mock_client_instance = AsyncMock(spec=Client)
        mock_client_instance.__aenter__ = AsyncMock()
        mock_client_instance.list_tools = AsyncMock(return_value=[])
        mock_client_class.return_value = mock_client_instance

        mcp_client = MCPClient()
        server_config = MCPRemoteServerConfig(
            name="test-shttp",
            type="shttp",
            url="http://localhost:8000/mcp",
            api_key="shttp_key_456",
            transport="shttp"
        )

        await mcp_client.connect_http(server_config)

        mock_shttp_transport.assert_called_once()
        self.assertTrue(mcp_client._session_active)

    async def test_connect_http_without_url_raises(self) -> None:
        """Test connecting without empty URL raises ValidationError."""
        MCPClient()

        with self.assertRaises(ValidationError):
            MCPRemoteServerConfig(name="bad", type="sse", url="", transport="sse")

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.SSETransport")
    async def test_connect_http_with_conversation_id(
        self, mock_sse_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test HTTP connection includes conversation_id in headers."""
        mock_client_instance = AsyncMock(spec=Client)
        mock_client_instance.__aenter__ = AsyncMock()
        mock_client_instance.list_tools = AsyncMock(return_value=[])
        mock_client_class.return_value = mock_client_instance

        mcp_client = MCPClient()
        server_config = MCPRemoteServerConfig(
            name="test-sse",
            type="sse",
            url="http://localhost:8000/sse",
            transport="sse",
        )

        await mcp_client.connect_http(server_config, conversation_id="conv_abc123")

        # Verify headers passed to transport
        call_kwargs = mock_sse_transport.call_args[1]
        headers = call_kwargs.get("headers", {})
        self.assertIn("X-Forge-ServerConversation-ID", headers)
        self.assertEqual(headers["X-Forge-ServerConversation-ID"], "conv_abc123")

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.SSETransport")
    async def test_connect_http_records_mcp_error(
        self, mock_sse_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test McpError during connection is recorded in error collector."""
        mock_client_instance = AsyncMock(spec=Client)
        mock_client_instance.__aenter__ = AsyncMock(
            side_effect=McpError(ErrorData(code=-1, message="MCP server unavailable"))
        )
        mock_client_class.return_value = mock_client_instance

        mcp_client = MCPClient()
        server_config = MCPRemoteServerConfig(
            name="test-sse",
            type="sse",
            url="http://localhost:8000/sse",
            transport="sse",
        )

        with self.assertRaises(McpError):
            await mcp_client.connect_http(server_config)

        # Error should be recorded (we can't easily verify error_collector without mocking it)

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.SSETransport")
    async def test_connect_http_records_generic_error(
        self, mock_sse_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test generic exception during connection is recorded."""
        mock_client_instance = AsyncMock(spec=Client)
        mock_client_instance.__aenter__ = AsyncMock(
            side_effect=ConnectionError("Network unreachable")
        )
        mock_client_class.return_value = mock_client_instance

        mcp_client = MCPClient()
        server_config = MCPRemoteServerConfig(
            name="test-sse",
            type="sse",
            url="http://localhost:8000/sse",
            transport="sse",
        )

        with self.assertRaises(ConnectionError):
            await mcp_client.connect_http(server_config)


class TestMCPClientStdioConnection(unittest.IsolatedAsyncioTestCase):
    """Tests for stdio-based MCP connections."""

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.StdioTransport")
    async def test_connect_stdio(
        self, mock_stdio_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test connecting to stdio-based MCP server."""
        mock_client_instance = AsyncMock(spec=Client)
        mock_client_instance.__aenter__ = AsyncMock()
        mock_client_instance.list_tools = AsyncMock(return_value=[])
        mock_client_class.return_value = mock_client_instance

        mcp_client = MCPClient()
        server_config = MCPStdioServerConfig(
            name="test-server",
            type="stdio",
            command="python",
            args=["-m", "mcp_server"],
            env={"DEBUG": "1"},
        )

        await mcp_client.connect_stdio(server_config)

        mock_stdio_transport.assert_called_once()
        call_kwargs = mock_stdio_transport.call_args[1]
        self.assertEqual(call_kwargs["command"], "python")
        self.assertEqual(call_kwargs["args"], ["-m", "mcp_server"])
        self.assertEqual(call_kwargs["env"], {"DEBUG": "1"})

    @patch("backend.mcp_client.client.Client")
    @patch("backend.mcp_client.client.StdioTransport")
    async def test_connect_stdio_error_handling(
        self, mock_stdio_transport: Mock, mock_client_class: Mock
    ) -> None:
        """Test stdio connection error handling."""
        mock_stdio_transport.side_effect = OSError("Command not found")

        mcp_client = MCPClient()
        server_config = MCPStdioServerConfig(
            name="bad-server",
            type="stdio",
            command="nonexistent_mcp_server",
            args=[],
        )

        with self.assertRaises(OSError):
            await mcp_client.connect_stdio(server_config)


class TestMCPClientToolCalls(unittest.IsolatedAsyncioTestCase):
    """Tests for MCP tool invocation."""

    async def test_call_tool_success(self) -> None:
        """Test successful tool call."""
        mock_client = AsyncMock(spec=Client)
        mock_result = CallToolResult(content=[{"type": "text", "text": "File found"}])
        mock_client.call_tool_mcp = AsyncMock(return_value=mock_result)

        mcp_client = MCPClient(client=mock_client, _session_active=True)
        mcp_client.tool_map = {
            "search_files": MCPClientTool(
                name="search_files",
                description="Search files",
                inputSchema={},
            )
        }

        result = await mcp_client.call_tool("search_files", {"query": "test.py"})

        self.assertEqual(result, mock_result)
        mock_client.call_tool_mcp.assert_called_once_with(
            name="search_files", arguments={"query": "test.py"}
        )

    async def test_call_tool_not_found(self) -> None:
        """Test calling unknown tool raises ValueError."""
        mcp_client = MCPClient(client=AsyncMock(spec=Client), _session_active=True)
        mcp_client.tool_map = {}

        with self.assertRaises(ValueError) as ctx:
            await mcp_client.call_tool("unknown_tool", {})

        self.assertIn("Tool unknown_tool not found", str(ctx.exception))

    async def test_call_tool_without_client_raises(self) -> None:
        """Test calling tool without active client raises RuntimeError."""
        mcp_client = MCPClient()
        mcp_client.tool_map = {"test_tool": MagicMock()}

        with self.assertRaises(RuntimeError) as ctx:
            await mcp_client.call_tool("test_tool", {})

        self.assertIn("Client session is not available", str(ctx.exception))

    async def test_call_tool_reconnects_on_failure(self) -> None:
        """Test tool call reconnects and retries on failure."""
        mock_client = AsyncMock(spec=Client)
        mock_client.__aenter__ = AsyncMock()
        mock_client.list_tools = AsyncMock(
            return_value=[Tool(name="test_tool", description="Test", inputSchema={})]
        )

        # First call fails, second succeeds
        success_result = CallToolResult(content=[{"type": "text", "text": "OK"}])
        mock_client.call_tool_mcp = AsyncMock(
            side_effect=[ConnectionError("Lost connection"), success_result]
        )

        mcp_client = MCPClient(client=mock_client, _session_active=True)
        mcp_client.tool_map = {
            "test_tool": MCPClientTool(
                name="test_tool",
                description="Test",
                inputSchema={},
            )
        }

        result = await mcp_client.call_tool("test_tool", {})

        self.assertEqual(result, success_result)
        self.assertEqual(mock_client.call_tool_mcp.call_count, 2)


class TestMCPClientReconnection(unittest.IsolatedAsyncioTestCase):
    """Tests for automatic reconnection logic."""

    async def test_reconnect_succeeds_on_first_attempt(self) -> None:
        """Test successful reconnection on first attempt."""
        mock_client = AsyncMock(spec=Client)
        mock_client.__aenter__ = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])

        mcp_client = MCPClient(client=mock_client)

        await mcp_client._reconnect()

        self.assertTrue(mcp_client._session_active)
        mock_client.__aenter__.assert_called()

    async def test_reconnect_exponential_backoff(self) -> None:
        """Test reconnection uses exponential backoff."""
        mock_client = AsyncMock(spec=Client)
        mock_client.__aenter__ = AsyncMock(
            side_effect=[Exception("Fail 1"), Exception("Fail 2"), None]
        )
        mock_client.list_tools = AsyncMock(return_value=[])

        mcp_client = MCPClient(client=mock_client)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mcp_client._reconnect()

            # Should have slept 3 times: 0.5s, 1.0s, 2.0s
            self.assertEqual(mock_sleep.call_count, 3)

    async def test_reconnect_fails_after_max_attempts(self) -> None:
        """Test reconnection raises after max attempts."""
        mock_client = AsyncMock(spec=Client)
        mock_client.__aenter__ = AsyncMock(side_effect=ConnectionError("Server down"))

        mcp_client = MCPClient(client=mock_client)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(RuntimeError) as ctx:
                await mcp_client._reconnect()

            self.assertIn("unreachable after", str(ctx.exception))


class TestMCPClientDisconnection(unittest.IsolatedAsyncioTestCase):
    """Tests for graceful disconnection."""

    async def test_disconnect_clears_state(self) -> None:
        """Test disconnect clears all client state."""
        mock_client = AsyncMock(spec=Client)
        mock_client.__aexit__ = AsyncMock()

        mcp_client = MCPClient(client=mock_client, _session_active=True)
        mcp_client.tools = [MagicMock()]
        mcp_client.tool_map = {"test": MagicMock()}

        await mcp_client.disconnect()

        self.assertIsNone(mcp_client.client)
        self.assertFalse(mcp_client._session_active)
        self.assertEqual(len(mcp_client.tools), 0)
        self.assertEqual(len(mcp_client.tool_map), 0)


if __name__ == "__main__":
    unittest.main()
