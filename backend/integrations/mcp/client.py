"""Model Context Protocol client wrapper for managing remote tool registries."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastmcp import Client
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
from mcp import McpError
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from backend.core.config.mcp_config import MCPServerConfig
from backend.core.logger import app_logger as logger
from backend.core.workspace_resolution import get_effective_workspace_root
from backend.integrations.mcp.error_collector import mcp_error_collector
from backend.integrations.mcp.tool import MCPClientTool

if TYPE_CHECKING:
    from mcp.types import CallToolResult

_MAX_RECONNECT_ATTEMPTS = 5
_BASE_BACKOFF_S = 0.5


def _is_exception_group(exc: BaseException) -> bool:
    """Return whether ``exc`` is a Python 3.11 ``BaseExceptionGroup``."""
    try:
        return isinstance(exc, BaseExceptionGroup)
    except NameError:  # pragma: no cover - Python < 3.11 compatibility
        return False


def _mcp_call_total_budget_sec() -> float:
    """Max wall-clock time for one ``call_tool`` (attempt + reconnect + retry).

    Override with ``APP_MCP_CALL_TOTAL_BUDGET_SEC``.
    """
    raw = os.getenv('APP_MCP_CALL_TOTAL_BUDGET_SEC', '180')
    try:
        v = float(raw)
        return v if v > 0 else 180.0
    except (TypeError, ValueError):
        return 180.0


def _mcp_reconnect_session_timeout_sec() -> float:
    """Per-attempt cap for ``_open_session`` + ``_populate_tools`` during reconnect.

    Override with ``APP_MCP_RECONNECT_SESSION_TIMEOUT_SEC``.
    """
    raw = os.getenv('APP_MCP_RECONNECT_SESSION_TIMEOUT_SEC', '90')
    try:
        v = float(raw)
        return v if v > 0 else 90.0
    except (TypeError, ValueError):
        return 90.0


class MCPClient(BaseModel):
    """MCP client that maintains a persistent session to the server.

    The session is opened on :meth:`connect_http` / :meth:`connect_stdio`
    and kept alive for the lifetime of the client.  :meth:`call_tool` reuses
    the same session.  If the session drops, the client will attempt to
    reconnect with exponential back-off.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    client: Client[Any] | None = None
    description: str = 'MCP client tools for server interaction'
    tools: list[MCPClientTool] = Field(default_factory=list)
    tool_map: dict[str, MCPClientTool] = Field(default_factory=dict)
    exposed_to_protocol: dict[str, str] = Field(default_factory=dict)
    _session_active: bool = False
    _mcp_alias_peers: list[Any] | None = PrivateAttr(default=None)
    _mcp_alias_reserved: frozenset[str] | None = PrivateAttr(default=None)
    _connect_kwargs: dict[str, Any] | None = None
    _server_config: MCPServerConfig | None = None

    # ------------------------------------------------------------------
    # Internal session management
    # ------------------------------------------------------------------

    def register_alias_context(
        self, peers: list[Any], reserved: frozenset[str]
    ) -> None:
        """Remember peer list and reserved names so reconnect can re-apply aliases."""
        self._mcp_alias_peers = peers
        self._mcp_alias_reserved = reserved

    def _reapply_mcp_tool_aliases(self) -> None:
        peers = self._mcp_alias_peers
        reserved = self._mcp_alias_reserved
        if peers is None or reserved is None:
            return
        from backend.integrations.mcp.mcp_tool_aliases import (
            prepare_mcp_tool_exposed_names,
        )

        prepare_mcp_tool_exposed_names(peers, set(reserved))

    async def _open_session(self) -> None:
        """Open the persistent session on the current ``self.client``."""
        if self.client is None:
            raise RuntimeError('Client not configured.')
        # Intentional: session lifecycle is open/close across multiple calls, not a single async with
        await self.client.__aenter__()  # pylint: disable=unnecessary-dunder-call
        self._session_active = True

    async def _close_client_context(self, cli: Client[Any]) -> None:
        """Close the active async context manager for the MCP client."""
        try:
            await cli.__aexit__(None, None, None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_exception_group(exc):
                # stdio MCP often ends with ExceptionGroup(BrokenResourceError); not an app bug.
                logger.debug('MCP session __aexit__ teardown: %s', exc)
            else:
                logger.warning('MCP session close failed: %s', exc, exc_info=True)

    async def _close_client_transport(self, cli: Client[Any]) -> None:
        """Close the underlying MCP transport."""
        try:
            await cli.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_exception_group(exc):
                logger.debug('MCP client.close() teardown: %s', exc)
            else:
                logger.debug('MCP client.close(): %s', exc, exc_info=True)

    async def _close_session(self) -> None:
        """Close the persistent session if active."""
        if self.client is None or not self._session_active:
            return
        cli = self.client
        try:
            try:
                await self._close_client_context(cli)
            except asyncio.CancelledError:
                logger.debug(
                    'MCP session __aexit__ cancelled during teardown; treating as closed'
                )

            try:
                await self._close_client_transport(cli)
            except asyncio.CancelledError:
                logger.debug(
                    'MCP client.close() cancelled during teardown; treating as closed'
                )
        finally:
            self._session_active = False

    async def _populate_tools(self) -> None:
        """Fetch available tools from the connected server."""
        if not self.client:
            raise RuntimeError('Session not initialized.')
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
            'Connected to MCP server with %d tools: %s',
            len(tools),
            [t.name for t in tools],
        )

    async def _rebuild_stdio_client(self) -> None:
        """Re-create the stdio transport and FastMCP client from the stored config.

        Called during reconnect when the child process has already exited
        (``keep_alive=False`` causes the subprocess to die after the initial
        tool-enumeration session).  Simply re-entering ``__aenter__`` on a dead
        transport will always fail; we have to spawn a fresh subprocess.
        """
        cfg = self._server_config
        if cfg is None or cfg.command is None:
            raise RuntimeError('No stdio server config available for reconnect.')
        cwd_path = get_effective_workspace_root()
        cwd: str | None
        if cwd_path is not None:
            cwd = str(cwd_path.resolve())
        else:
            try:
                cwd = str(Path.cwd().resolve())
            except OSError:
                cwd = None
        transport = StdioTransport(
            command=cfg.command,
            args=cfg.args or [],
            env=cfg.env,
            cwd=cwd,
            keep_alive=False,
        )
        self.client = Client(transport, timeout=_mcp_reconnect_session_timeout_sec())

    async def _resync_session_after_disconnect(self) -> None:
        """Re-enter session and refresh tool list (used after transport drop)."""
        # For stdio servers the child subprocess exits after the initial
        # tool-enumeration (keep_alive=False).  Re-entering __aenter__ on the
        # dead transport will always raise BrokenResourceError.  Rebuild the
        # transport (i.e. re-launch the subprocess) first.
        if self._server_config is not None and self._server_config.type == 'stdio':
            await self._rebuild_stdio_client()
        await self._open_session()
        await self._populate_tools()
        self._reapply_mcp_tool_aliases()

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential back-off."""
        await self._close_session()
        session_timeout = _mcp_reconnect_session_timeout_sec()
        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            delay = _BASE_BACKOFF_S * (2 ** (attempt - 1))
            logger.warning(
                'MCP reconnect attempt %d/%d in %.1fs ...',
                attempt,
                _MAX_RECONNECT_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
            try:
                await asyncio.wait_for(
                    self._resync_session_after_disconnect(),
                    timeout=session_timeout,
                )
                logger.info('MCP reconnected on attempt %d', attempt)
                return
            except asyncio.TimeoutError:
                logger.warning(
                    'MCP reconnect attempt %d: session sync timed out after %.1fs',
                    attempt,
                    session_timeout,
                )
            except Exception as exc:
                logger.warning('MCP reconnect attempt %d failed: %s', attempt, exc)
        raise RuntimeError(
            f'MCP server unreachable after {_MAX_RECONNECT_ATTEMPTS} reconnect attempts.'
        )

    # ------------------------------------------------------------------
    # Public API — connect
    # ------------------------------------------------------------------

    async def connect_http(
        self,
        server: MCPServerConfig,
        conversation_id: str | None = None,
        connect_timeout: float = 30.0,
    ) -> None:
        """Connect to MCP server using SHTTP or SSE transport.

        Args:
            server: Server configuration
            conversation_id: Optional conversation ID
            connect_timeout: Connection timeout in seconds

        Raises:
            ValueError: If server URL is missing
            McpError: On MCP-specific errors
            Exception: On other connection errors

        """
        server_url = server.url
        if not server_url:
            msg = 'Server URL is required.'
            raise ValueError(msg)

        try:
            headers = self._build_http_headers(server.api_key, conversation_id)
            transport = self._create_http_transport(server, server_url, headers)
            self.client = Client(transport, timeout=connect_timeout)
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
    ) -> dict[str, str]:
        """Build HTTP headers for connection."""
        headers: dict[str, str] = {}
        if api_key:
            headers.update(
                {
                    'Authorization': f'Bearer {api_key}',
                    's': api_key,
                },
            )
        if conversation_id:
            headers['X-App-ServerConversation-ID'] = conversation_id
        return headers

    def _create_http_transport(
        self, server: MCPServerConfig, server_url: str, headers: dict[str, str]
    ) -> StreamableHttpTransport | SSETransport:
        """Create appropriate HTTP transport."""
        if server.transport == 'shttp':
            return StreamableHttpTransport(url=server_url, headers=headers or None)
        return SSETransport(url=server_url, headers=headers or None)

    def _handle_connection_error(
        self,
        server_url: str,
        server: MCPServerConfig,
        error: Exception,
        is_mcp_error: bool = False,
    ) -> None:
        """Handle and record connection errors."""
        error_prefix = 'McpError' if is_mcp_error else 'Error'
        error_msg = f'{error_prefix} connecting to {server_url}: {error}'
        logger.error(error_msg)

        mcp_error_collector.add_error(
            server_name=server_url,
            server_type=server.transport,
            error_message=error_msg,
            exception_details=str(error),
        )

    async def connect_stdio(
        self, server: MCPServerConfig, connect_timeout: float = 30.0
    ) -> None:
        """Connect to MCP server using stdio transport."""
        try:
            assert server.command is not None
            # keep_alive=False: default True skips transport.disconnect() on session exit,
            # leaving _stdio_transport_connect_task to die with BrokenResourceError and
            # asyncio "Task exception was never retrieved" (fastmcp client/transports.py).
            cwd_path = get_effective_workspace_root()
            cwd: str | None
            if cwd_path is not None:
                cwd = str(cwd_path.resolve())
            else:
                try:
                    cwd = str(Path.cwd().resolve())
                except OSError:
                    cwd = None
            transport = StdioTransport(
                command=server.command,
                args=server.args or [],
                env=server.env,
                cwd=cwd,
                keep_alive=False,
            )
            self.client = Client(transport, timeout=connect_timeout)
            self._server_config = server
            await self._open_session()
            await self._populate_tools()
        except Exception as e:
            server_name = getattr(
                server, 'name', f'{server.command} {" ".join(server.args or [])}'
            )
            error_msg = f'Failed to connect to stdio server {server_name}: {e}'
            logger.error(error_msg)
            mcp_error_collector.add_error(
                server_name=server_name,
                server_type='stdio',
                error_message=error_msg,
                exception_details=str(e),
            )
            raise

    # ------------------------------------------------------------------
    # Public API — call tool
    # ------------------------------------------------------------------

    # Per-call timeout (seconds).  Override via subclass or instance attribute.
    CALL_TIMEOUT: float = 60.0

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> CallToolResult:
        """Call a tool on the MCP server, reconnecting if the session dropped.

        Each attempt uses ``asyncio.wait_for`` with ``CALL_TIMEOUT`` seconds.
        Reconnect steps are also bounded (see ``APP_MCP_RECONNECT_SESSION_TIMEOUT_SEC``).
        The entire invoke+reconnect+retry sequence is capped by
        ``APP_MCP_CALL_TOTAL_BUDGET_SEC`` so a dead server cannot stall the agent.
        """
        if tool_name not in self.tool_map:
            msg = f'Tool {tool_name} not found.'
            raise ValueError(msg)
        if not self.client:
            msg = 'Client session is not available.'
            raise RuntimeError(msg)

        wire_name = self.exposed_to_protocol.get(tool_name, tool_name)

        async def _call_once():
            assert self.client is not None
            return await asyncio.wait_for(
                self.client.call_tool_mcp(name=wire_name, arguments=args),
                timeout=self.CALL_TIMEOUT,
            )

        async def _invoke_with_retry() -> CallToolResult:
            try:
                return await _call_once()
            except asyncio.TimeoutError:
                logger.warning(
                    'MCP call_tool(%s) timed out after %.1fs — reconnect + single retry',
                    tool_name,
                    self.CALL_TIMEOUT,
                )
            except (ConnectionError, OSError) as exc:
                # Transport-level drops only; do not retry arbitrary exceptions (risk of
                # duplicate side effects on mutating tools if the server already applied the call).
                logger.warning(
                    'MCP call_tool(%s) transport error (%s): %s — reconnect + single retry',
                    tool_name,
                    type(exc).__name__,
                    exc,
                )
            except RuntimeError as exc:
                # On Windows with ProactorEventLoop, a broken stdio subprocess pipe raises
                # RuntimeError("Event loop is closed") — misleading name, it's the IOCP
                # transport handle becoming invalid. Treat it like a transport drop.
                if 'closed' not in str(exc).lower():
                    raise
                logger.warning(
                    'MCP call_tool(%s) RuntimeError (Windows transport): %s — reconnect + single retry',
                    tool_name,
                    exc,
                )

            await self._reconnect()
            return await _call_once()

        budget = _mcp_call_total_budget_sec()
        try:
            return await asyncio.wait_for(_invoke_with_retry(), timeout=budget)
        except asyncio.TimeoutError:
            logger.error(
                'MCP call_tool(%s) exceeded total budget %.1fs '
                '(per-attempt timeout %.1fs; includes reconnect/retry)',
                tool_name,
                budget,
                self.CALL_TIMEOUT,
            )
            raise

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
        self.exposed_to_protocol = {}
        self._mcp_alias_peers = None
        self._mcp_alias_reserved = None
        logger.info('MCP client disconnected.')
