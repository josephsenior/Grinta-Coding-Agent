"""Model Context Protocol client wrapper for managing remote tool registries."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastmcp import Client
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
from mcp import McpError
from pydantic import BaseModel, ConfigDict, Field

from backend.core.config.mcp_config import (
    MCPSHTTPServerConfig,
    MCPSSEServerConfig,
    MCPStdioServerConfig,
)
from backend.core.logger import FORGE_logger as logger
from backend.mcp.error_collector import mcp_error_collector
from backend.mcp.tool import MCPClientTool

if TYPE_CHECKING:
    from mcp.types import CallToolResult

_MAX_RECONNECT_ATTEMPTS = 5
_BASE_BACKOFF_S = 0.5


class MCPClient(BaseModel):
    """MCP client that maintains a persistent session to the server.

    The session is opened on :meth:`connect_http` / :meth:`connect_stdio`
    and kept alive for the lifetime of the client.  :meth:`call_tool` reuses
    the same session.  If the session drops, the client will attempt to
    reconnect with exponential back-off.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    client: Client | None = None
    description: str = "MCP client tools for server interaction"
    tools: list[MCPClientTool] = Field(default_factory=list)
    tool_map: dict[str, MCPClientTool] = Field(default_factory=dict)
    _session_active: bool = False
    _connect_kwargs: dict | None = None
    _server_config: (
        MCPStdioServerConfig | MCPSSEServerConfig | MCPSHTTPServerConfig | None
    ) = None

    # ------------------------------------------------------------------
    # Internal session management
    # ------------------------------------------------------------------

    async def _open_session(self) -> None:
        """Open the persistent session on the current ``self.client``."""
        if self.client is None:
            raise RuntimeError("Client not configured.")
        await self.client.__aenter__()
        self._session_active = True

    async def _close_session(self) -> None:
        """Close the persistent session if active."""
        if self.client is not None and self._session_active:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_active = False

    async def _populate_tools(self) -> None:
        """Fetch available tools from the connected server."""
        if not self.client:
            raise RuntimeError("Session not initialized.")
        tools = await self.client.list_tools()
        self.tools = []
        self.tool_map = {}
        for tool in tools:
            server_tool = MCPClientTool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.inputSchema,
            )
            self.tool_map[tool.name] = server_tool
            self.tools.append(server_tool)
        logger.info(
            "Connected to MCP server with %d tools: %s",
            len(tools),
            [t.name for t in tools],
        )

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential back-off."""
        await self._close_session()
        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            delay = _BASE_BACKOFF_S * (2 ** (attempt - 1))
            logger.warning(
                "MCP reconnect attempt %d/%d in %.1fs ...",
                attempt,
                _MAX_RECONNECT_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
            try:
                await self._open_session()
                await self._populate_tools()
                logger.info("MCP reconnected on attempt %d", attempt)
                return
            except Exception as exc:
                logger.warning("MCP reconnect attempt %d failed: %s", attempt, exc)
        raise RuntimeError(
            f"MCP server unreachable after {_MAX_RECONNECT_ATTEMPTS} reconnect attempts."
        )

    # ------------------------------------------------------------------
    # Public API — connect
    # ------------------------------------------------------------------

    async def connect_http(
        self,
        server: MCPSSEServerConfig | MCPSHTTPServerConfig,
        conversation_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Connect to MCP server using SHTTP or SSE transport.

        Args:
            server: Server configuration
            conversation_id: Optional conversation ID
            timeout: Connection timeout in seconds

        Raises:
            ValueError: If server URL is missing
            McpError: On MCP-specific errors
            Exception: On other connection errors

        """
        server_url = server.url
        if not server_url:
            msg = "Server URL is required."
            raise ValueError(msg)

        try:
            headers = self._build_http_headers(server.api_key, conversation_id)
            transport = self._create_http_transport(server, server_url, headers)
            self.client = Client(transport, timeout=timeout)
            self._server_config = server
            await self._open_session()
            await self._populate_tools()
        except McpError as e:
            self._handle_connection_error(server_url, server, e, is_mcp_error=True)
            raise
        except Exception as e:
            self._handle_connection_error(server_url, server, e, is_mcp_error=False)
            raise

    def _build_http_headers(
        self, api_key: str | None, conversation_id: str | None
    ) -> dict:
        """Build HTTP headers for connection."""
        headers = {}
        if api_key:
            headers.update(
                {
                    "Authorization": f"Bearer {api_key}",
                    "s": api_key,
                    "X-Session-API-Key": api_key,
                },
            )
        if conversation_id:
            headers["X-Forge-ServerConversation-ID"] = conversation_id
        return headers

    def _create_http_transport(self, server, server_url: str, headers: dict):
        """Create appropriate HTTP transport."""
        if isinstance(server, MCPSHTTPServerConfig):
            return StreamableHttpTransport(url=server_url, headers=headers or None)
        return SSETransport(url=server_url, headers=headers or None)

    def _handle_connection_error(
        self, server_url: str, server, error: Exception, is_mcp_error: bool = False
    ) -> None:
        """Handle and record connection errors."""
        error_prefix = "McpError" if is_mcp_error else "Error"
        error_msg = f"{error_prefix} connecting to {server_url}: {error}"
        logger.error(error_msg)

        server_type = "shttp" if isinstance(server, MCPSHTTPServerConfig) else "sse"
        mcp_error_collector.add_error(
            server_name=server_url,
            server_type=server_type,
            error_message=error_msg,
            exception_details=str(error),
        )

    async def connect_stdio(
        self, server: MCPStdioServerConfig, timeout: float = 30.0
    ) -> None:
        """Connect to MCP server using stdio transport."""
        try:
            transport = StdioTransport(
                command=server.command, args=server.args or [], env=server.env
            )
            self.client = Client(transport, timeout=timeout)
            self._server_config = server
            await self._open_session()
            await self._populate_tools()
        except Exception as e:
            server_name = getattr(
                server, "name", f"{server.command} {' '.join(server.args or [])}"
            )
            error_msg = f"Failed to connect to stdio server {server_name}: {e}"
            logger.error(error_msg)
            mcp_error_collector.add_error(
                server_name=server_name,
                server_type="stdio",
                error_message=error_msg,
                exception_details=str(e),
            )
            raise

    # ------------------------------------------------------------------
    # Public API — call tool
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, args: dict) -> CallToolResult:
        """Call a tool on the MCP server, reconnecting if the session dropped."""
        if tool_name not in self.tool_map:
            msg = f"Tool {tool_name} not found."
            raise ValueError(msg)
        if not self.client:
            msg = "Client session is not available."
            raise RuntimeError(msg)

        try:
            return await self.client.call_tool_mcp(name=tool_name, arguments=args)
        except Exception as exc:
            logger.warning(
                "MCP call_tool(%s) failed: %s — attempting reconnect", tool_name, exc
            )
            await self._reconnect()
            # Retry once after reconnect
            return await self.client.call_tool_mcp(name=tool_name, arguments=args)

    # ------------------------------------------------------------------
    # Public API — disconnect
    # ------------------------------------------------------------------

    async def disconnect(self) -> None:
        """Gracefully close the MCP session."""
        await self._close_session()
        self.client = None
        self._session_active = False
        self.tools = []
        self.tool_map = {}
        logger.info("MCP client disconnected.")
