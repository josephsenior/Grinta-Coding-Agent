"""Configuration models for Model Context Protocol (MCP) servers and clients."""

from __future__ import annotations

import os
import re
import shlex
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend._canonical import CanonicalModelMetaclass
from backend.core.constants import DEFAULT_FORGE_MCP_CONFIG_CLS

if TYPE_CHECKING:
    from backend.core.config.forge_config import ForgeConfig
from backend.utils.import_utils import get_impl


def _validate_mcp_url(url: str) -> str:
    """Shared URL validation logic for MCP servers with type-safe validation."""
    from backend.core.type_safety.type_safety import validate_non_empty_string

    # Use type-safe validation
    try:
        validate_non_empty_string(url, name="url")
    except ValueError as e:
        raise ValueError(f"URL cannot be empty: {e}") from e
    url = url.strip()
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            msg = "URL must include a scheme (http:// or https://)"
            raise ValueError(msg)
        if not parsed.netloc:
            msg = "URL must include a valid domain/host"
            raise ValueError(msg)
        if parsed.scheme not in ["http", "https", "ws", "wss"]:
            msg = "URL scheme must be http, https, ws, or wss"
            raise ValueError(msg)
        return url
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        msg = f"Invalid URL format: {e!s}"
        raise ValueError(msg) from e


class MCPSSEServerConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for a single MCP server.

    Attributes:
        url: The server URL
        api_key: Optional API key for authentication

    """

    url: str
    api_key: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format for MCP servers."""
        return _validate_mcp_url(v)


class MCPStdioServerConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for a MCP server that uses stdio.

    Attributes:
        name: The name of the server
        command: The command to run the server
        args: The arguments to pass to the server
        env: The environment variables to set for the server

    """

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def validate_server_name(cls, v: str) -> str:
        """Validate server name for stdio MCP servers with type-safe validation."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        # Use type-safe validation
        try:
            validate_non_empty_string(v, name="server_name")
        except ValueError as e:
            raise ValueError(f"Server name cannot be empty: {e}") from e

        v = v.strip()
        if not re.match("^[a-zA-Z0-9_-]+$", v):
            msg = "Server name can only contain letters, numbers, hyphens, and underscores"
            raise ValueError(msg)
        return v

    @field_validator("command", mode="before")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Validate command for stdio MCP servers with type-safe validation."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        # Use type-safe validation
        try:
            validate_non_empty_string(v, name="command")
        except ValueError as e:
            raise ValueError(f"Command cannot be empty: {e}") from e

        v = v.strip()
        if " " in v:
            msg = "Command should be a single executable without spaces (use arguments field for parameters)"
            raise ValueError(
                msg,
            )
        return v

    @field_validator("args", mode="before")
    @classmethod
    def parse_args(cls, v) -> list[str]:
        """Parse arguments from string or return list as-is.

        Supports shell-like argument parsing using shlex.split().

        Examples:
        - "-y mcp-remote https://example.com"
        - '--config "path with spaces" --debug'
        - "arg1 arg2 arg3"

        """
        if isinstance(v, str):
            if not v.strip():
                return []
            v = v.strip()
            try:
                return shlex.split(v)
            except ValueError as e:
                msg = f"""Invalid argument format: {
                    e!s
                }. Use shell-like format, e.g., "arg1 arg2" or '--config "value with spaces"'"""
                raise ValueError(
                    msg,
                ) from e
        return v or []

    @field_validator("env", mode="before")
    @classmethod
    def parse_env(cls, v) -> dict[str, str]:
        """Parse environment variables from string or return dict as-is."""
        if not isinstance(v, str):
            return v or {}
        if not v.strip():
            return {}
        env = {}
        for pair in v.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                msg = f"Environment variable '{pair}' must be in KEY=VALUE format"
                raise ValueError(msg)
            key, value = pair.split("=", 1)
            key = key.strip()
            if not key:
                msg = "Environment variable key cannot be empty"
                raise ValueError(msg)
            if not re.match("^[a-zA-Z_][a-zA-Z0-9_]*$", key):
                msg = f"Invalid environment variable name '{key}'. Must start with letter or underscore, contain only alphanumeric characters and underscores"
                raise ValueError(
                    msg,
                )
            env[key] = value
        return env

    def __eq__(self, other):
        """Override equality operator to compare server configurations.

        Two server configurations are considered equal if they have the same
        name, command, args, and env values. The order of args is important,
        but the order of env variables is not.
        """
        if not isinstance(other, MCPStdioServerConfig):
            return False
        return (
            self.name == other.name
            and self.command == other.command
            and (self.args == other.args)
            and (set(self.env.items()) == set(other.env.items()))
        )


class MCPSHTTPServerConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for HTTP-based MCP servers.

    Attributes:
        url: URL of the MCP HTTP server
        api_key: Optional API key for authentication

    """

    url: str
    api_key: str | None = None

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format for MCP servers."""
        return _validate_mcp_url(v)


class MCPConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for MCP (Message Control Protocol) settings.

    Attributes:
        sse_servers: List of MCP SSE server configs
        stdio_servers: List of MCP stdio server configs. These servers will be added to the MCP Router running inside runtime container.
        shttp_servers: List of MCP HTTP server configs.

    """

    sse_servers: list[MCPSSEServerConfig] = Field(default_factory=list)
    stdio_servers: list[MCPStdioServerConfig] = Field(default_factory=list)
    shttp_servers: list[MCPSHTTPServerConfig] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")

    @staticmethod
    def _normalize_servers(servers_data: list[dict | str]) -> list[dict]:
        """Normalize SSE server configurations into a consistent format."""
        normalized = []
        for server in servers_data:
            if isinstance(server, str):
                normalized.append({"url": server})
            else:
                normalized.append(server)
        return normalized

    @model_validator(mode="before")
    @classmethod
    def convert_string_urls(cls, data):
        """Convert string URLs to MCPSSEServerConfig objects."""
        if isinstance(data, dict):
            if "sse_servers" in data:
                data["sse_servers"] = cls._normalize_servers(data["sse_servers"])
            if "shttp_servers" in data:
                data["shttp_servers"] = cls._normalize_servers(data["shttp_servers"])
        return data

    def validate_servers(self) -> None:
        """Validate that server URLs are valid and unique."""
        urls = [server.url for server in self.sse_servers]
        if len(set(urls)) != len(urls):
            msg = "Duplicate MCP server URLs are not allowed"
            raise ValueError(msg)
        for url in urls:
            try:
                result = urlparse(url)
                if not all([result.scheme, result.netloc]):
                    msg = f"Invalid URL format: {url}"
                    raise ValueError(msg)
            except Exception as e:
                msg = f"Invalid URL {url}: {e!s}"
                raise ValueError(msg) from e

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, MCPConfig]:
        """Create a mapping of MCPConfig instances from a toml dictionary representing the [mcp] section.

        The configuration is built from all keys in data.

        Returns:
            dict[str, MCPConfig]: A mapping where the key "mcp" corresponds to the [mcp] configuration

        """
        mcp_mapping: dict[str, MCPConfig] = {}
        try:
            if "sse_servers" in data:
                data["sse_servers"] = cls._normalize_servers(data["sse_servers"])
                servers: list[
                    MCPSSEServerConfig | MCPStdioServerConfig | MCPSHTTPServerConfig
                ] = [MCPSSEServerConfig(**server) for server in data["sse_servers"]]
                data["sse_servers"] = servers
            if "stdio_servers" in data:
                servers = [
                    MCPStdioServerConfig(**server) for server in data["stdio_servers"]
                ]
                data["stdio_servers"] = servers
            if "shttp_servers" in data:
                data["shttp_servers"] = cls._normalize_servers(data["shttp_servers"])
                servers = [
                    MCPSHTTPServerConfig(**server) for server in data["shttp_servers"]
                ]
                data["shttp_servers"] = servers
            mcp_config = MCPConfig.model_validate(data)
            mcp_config.validate_servers()
            mcp_mapping["mcp"] = cls(
                sse_servers=mcp_config.sse_servers,
                stdio_servers=mcp_config.stdio_servers,
                shttp_servers=mcp_config.shttp_servers,
            )
        except ValidationError as e:
            msg = f"Invalid MCP configuration: {e}"
            raise ValueError(msg) from e
        return mcp_mapping

    def merge(self, other: MCPConfig):
        """Merge this config with another MCP config.

        Args:
            other: MCP config to merge

        Returns:
            New merged MCPConfig

        """
        return MCPConfig(
            sse_servers=self.sse_servers + other.sse_servers,
            stdio_servers=self.stdio_servers + other.stdio_servers,
            shttp_servers=self.shttp_servers + other.shttp_servers,
        )


class ForgeMCPConfig:
    """Utility class for creating default Forge MCP configurations."""

    @staticmethod
    def create_default_mcp_server_config(
        host: str,
        config: ForgeConfig,
        user_id: str | None = None,
    ) -> tuple[MCPSHTTPServerConfig | None, list[MCPStdioServerConfig]]:
        """Create a default MCP server configuration.

        Args:
            host: Host string
            config: ForgeConfig
            user_id: Optional user ID for the MCP server
        Returns:
            tuple[MCPSHTTPServerConfig | None, list[MCPStdioServerConfig]]: A tuple containing the default SHTTP server configuration (or None) and a list of MCP stdio server configurations

        """
        stdio_servers: list[MCPStdioServerConfig] = []
        shttp_servers = MCPSHTTPServerConfig(url=f"http://{host}/mcp/mcp", api_key=None)
        return (shttp_servers, stdio_servers)


FORGE_mcp_config_cls = os.environ.get(
    "FORGE_MCP_CONFIG_CLS",
    DEFAULT_FORGE_MCP_CONFIG_CLS,
)
ForgeMCPConfigImpl = get_impl(ForgeMCPConfig, FORGE_mcp_config_cls)

__all__ = [
    "MCPSSEServerConfig",
    "MCPStdioServerConfig",
    "MCPSHTTPServerConfig",
    "MCPConfig",
    "ForgeMCPConfig",
    "ForgeMCPConfigImpl",
]
