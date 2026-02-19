"""MCP Proxy Manager for forge.

This module provides a manager class for handling FastMCP proxy instances,
including initialization, configuration, and mounting to FastAPI applications.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from anyio import get_cancelled_exc_class
from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger as fastmcp_get_logger

from backend.core.pydantic_compat import model_dump_with_options

if TYPE_CHECKING:
    from fastapi import FastAPI

    from backend.core.config.mcp_config import MCPStdioServerConfig

logger = logging.getLogger(__name__)
fastmcp_logger = fastmcp_get_logger("fastmcp")


class MCPProxyManager:
    """Manager for FastMCP proxy instances.

    This class encapsulates all the functionality related to creating, configuring,
    and managing FastMCP proxy instances, including mounting them to FastAPI applications.
    """

    def __init__(
        self,
        auth_enabled: bool = False,
        api_key: str | None = None,
        logger_level: int | None = None,
    ) -> None:
        """Initialize the MCP Proxy Manager.

        Args:
            name: Name of the proxy server
            auth_enabled: Whether authentication is enabled
            api_key: API key for authentication (required if auth_enabled is True)
            logger_level: Logging level for the FastMCP logger

        """
        self.auth_enabled = auth_enabled
        self.api_key = api_key
        self.proxy: FastMCP | None = None
        self.config: dict[str, Any] = {"mcpServers": {}}
        if logger_level is not None:
            fastmcp_logger.setLevel(logger_level)

    def initialize(self) -> None:
        """Initialize the FastMCP proxy with the current configuration."""
        if not self.config["mcpServers"]:
            logger.info(
                "No MCP servers configured for FastMCP Proxy, skipping initialization."
            )
            return
        self.proxy = FastMCP.as_proxy(
            self.config, auth_enabled=self.auth_enabled, api_key=self.api_key
        )
        logger.info("FastMCP Proxy initialized successfully")

    async def mount_to_app(
        self, app: FastAPI, allow_origins: list[str] | None = None
    ) -> None:
        """Mount the SSE server app to a FastAPI application.

        Args:
            app: FastAPI application to mount to
            allow_origins: List of allowed origins for CORS

        """
        if not self.config["mcpServers"]:
            logger.info("No MCP servers configured for FastMCP Proxy, skipping mount.")
            return
        if not self.proxy:
            msg = "FastMCP Proxy is not initialized"
            raise ValueError(msg)

        def close_on_double_start(app):
            """Wrap ASGI app to guard against duplicate response start events."""

            async def wrapped(scope, receive, send) -> None:
                """ASGI wrapper that intercepts http.response.start messages."""
                start_sent = False

                async def check_send(message) -> None:
                    """Proxy send coroutine raising if duplicate start detected."""
                    nonlocal start_sent
                    if message["type"] == "http.response.start":
                        if start_sent:
                            msg = "closed because of double http.response.start (mcp issue https://github.com/modelcontextprotocol/python-sdk/issues/883)"
                            raise get_cancelled_exc_class()(
                                msg,
                            )
                        start_sent = True
                    await send(message)

                await app(scope, receive, check_send)

            return wrapped

        mcp_app = close_on_double_start(
            self.proxy.http_app(path="/sse", transport="sse")
        )
        app.mount("/mcp", mcp_app)
        routes_to_remove = [
            route
            for route in list(app.routes)
            if getattr(route, "path", None) == "/mcp"
        ]
        for route in routes_to_remove:
            app.routes.remove(route)
        app.mount("/", mcp_app)
        logger.info("Mounted FastMCP Proxy app at /mcp")

    async def update_and_remount(
        self,
        app: FastAPI,
        stdio_servers: list[MCPStdioServerConfig],
        allow_origins: list[str] | None = None,
    ) -> None:
        """Update the tools configuration and remount the proxy to the app.

        This is a convenience method that combines updating the tools,
        shutting down the existing proxy, initializing a new one, and
        mounting it to the app.

        Args:
            app: FastAPI application to mount to
            stdio_servers: List of stdio server configurations
            allow_origins: List of allowed origins for CORS

        """
        tools = {t.name: model_dump_with_options(t) for t in stdio_servers}
        self.config["mcpServers"] = tools
        del self.proxy
        self.proxy = None
        self.initialize()
        await self.mount_to_app(app, allow_origins)
