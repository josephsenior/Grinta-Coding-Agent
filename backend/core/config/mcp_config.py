"""Configuration models for Model Context Protocol (MCP) servers and clients."""

from __future__ import annotations

import os
import re
import shlex
from typing import TYPE_CHECKING, Literal
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
from backend.core.logger import forge_logger as logger

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


class MCPServerConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Unified configuration for MCP servers (stdio, SSE, or sHTTP).

    Attributes:
        name: The server name (required for stdio, optional for remote)
        type: Server type - stdio, sse, or shttp
        command: Command to run (stdio only)
        args: Arguments to pass to command (stdio only)
        env: Environment variables (stdio only)
        url: Server URL (sse and shttp only)
        api_key: Optional API key (sse and shttp only)
        transport: Transport protocol for shttp (sse or shttp, defaults to sse)

    """

    name: str
    type: Literal["stdio", "sse", "shttp"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    api_key: str | None = None
    transport: Literal["sse", "shttp"] = "sse"

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate server name."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        try:
            validate_non_empty_string(v, name="name")
        except ValueError as e:
            raise ValueError(f"Server name cannot be empty: {e}") from e

        v = v.strip()
        if not re.match("^[a-zA-Z0-9_-]+$", v):
            msg = "Server name can only contain letters, numbers, hyphens, and underscores"
            raise ValueError(msg)
        return v

    @field_validator("command", mode="before")
    @classmethod
    def validate_command(cls, v: str | None) -> str | None:
        """Validate command for stdio servers."""
        if v is None:
            return None
        from backend.core.type_safety.type_safety import validate_non_empty_string

        try:
            validate_non_empty_string(v, name="command")
        except ValueError as e:
            raise ValueError(f"Command cannot be empty: {e}") from e

        v = v.strip()
        if " " in v:
            msg = "Command should be a single executable without spaces (use arguments field for parameters)"
            raise ValueError(msg)
        return v

    @field_validator("args", mode="before")
    @classmethod
    def parse_args(cls, v) -> list[str]:
        """Parse arguments from string or return list as-is."""
        if isinstance(v, str):
            if not v.strip():
                return []
            v = v.strip()
            try:
                return shlex.split(v)
            except ValueError as e:
                msg = f"Invalid argument format: {e!s}. Use shell-like format, e.g., \"arg1 arg2\" or '--config \"value with spaces\"'"
                raise ValueError(msg) from e
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
                raise ValueError(msg)
            env[key] = value
        return env

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        """Validate URL format for remote MCP servers."""
        if v is None:
            return None
        return _validate_mcp_url(v)

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> MCPServerConfig:
        """Ensure required fields are present for the server type."""
        if self.type == "stdio":
            if not self.command:
                msg = "stdio servers must specify 'command'"
                raise ValueError(msg)
        elif self.type in ("sse", "shttp"):
            if not self.url:
                msg = f"{self.type} servers must specify 'url'"
                raise ValueError(msg)
            if self.type == "sse":
                self.transport = "sse"
        return self

    @classmethod
    def from_dict(cls, name: str, data: dict) -> MCPServerConfig:
        """Create MCPServerConfig from a dictionary (e.g. from config.json)."""
        config = data.copy()
        config["name"] = name
        if "command" in config and "type" not in config:
            config["type"] = "stdio"
        elif "url" in config and "type" not in config:
            config["type"] = "sse"
        return cls(**config)

    def __eq__(self, other):
        """Override equality operator to compare server configurations."""
        if not isinstance(other, MCPServerConfig):
            return False
        return (
            self.name == other.name
            and self.type == other.type
            and self.command == other.command
            and self.args == other.args
            and set(self.env.items()) == set(other.env.items())
            and self.url == other.url
            and self.api_key == other.api_key
            and self.transport == other.transport
        )


# Backward compat: type aliases for imports (mark as deprecated)
MCPRemoteServerConfig = MCPServerConfig
MCPStdioServerConfig = MCPServerConfig


class MCPConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for MCP (Message Control Protocol) settings.

    Attributes:
        enabled: Whether MCP is enabled
        servers: List of MCP server configurations

    """

    enabled: bool = False
    servers: list[MCPServerConfig] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_server_lists(cls, data):
        """Support legacy MCP config formats.

        Historically, MCP servers were provided as separate lists like
        ``stdio_servers`` / ``sse_servers`` / ``shttp_servers``. The current
        unified format uses a single ``servers`` list. This coercion allows
        older config sources (including playbook metadata) to be parsed.
        """
        if not isinstance(data, dict):
            return data

        legacy_keys = ("stdio_servers", "sse_servers", "shttp_servers")
        if not any(k in data for k in legacy_keys):
            return data

        servers = list(data.get("servers") or [])

        def _extend_from(key: str, server_type: str) -> None:
            items = data.get(key) or []
            if isinstance(items, dict):
                items = list(items.values())
            for item in items:
                if not isinstance(item, dict):
                    continue
                srv = dict(item)
                srv.setdefault("type", server_type)
                servers.append(srv)

        _extend_from("stdio_servers", "stdio")
        _extend_from("sse_servers", "sse")
        _extend_from("shttp_servers", "shttp")

        coerced = dict(data)
        coerced["servers"] = servers
        for k in legacy_keys:
            coerced.pop(k, None)
        coerced.setdefault("enabled", bool(servers))
        return coerced

    def validate_servers(self) -> None:
        """Validate that server URLs (for remote servers) are unique."""
        urls = [s.url for s in self.servers if s.url]
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
        """Create MCPConfig from [mcp] section of toml file.

        Filters out stdio servers on Windows unless explicitly enabled.

        Returns:
            dict[str, MCPConfig]: A mapping where key "mcp" contains the config

        """
        import platform
        import json

        _known_keys = {"enabled", "servers"}
        unknown = set(data) - _known_keys
        if unknown:
            msg = f"Invalid MCP configuration: unknown keys: {', '.join(sorted(unknown))}"
            raise ValueError(msg)

        mcp_mapping: dict[str, MCPConfig] = {}
        try:
            enabled = data.get("enabled", False)
            servers_data = data.get("servers", [])
            if isinstance(servers_data, dict):
                # Handle case where single server is a dict
                servers_data = [servers_data]

            servers = [MCPServerConfig(**s) for s in servers_data]

            # Load additional servers from backend/runtime/mcp/config.json if it exists
            mcp_json_path = os.path.join("backend", "runtime", "mcp", "config.json")
            if os.path.exists(mcp_json_path):
                try:
                    with open(mcp_json_path, encoding="utf-8") as f:
                        mcp_json = json.load(f)
                        if "mcpServers" in mcp_json:
                            existing_names = {s.name for s in servers}
                            for name, srv_data in mcp_json["mcpServers"].items():
                                if name == "default":
                                    continue
                                if name not in existing_names:
                                    servers.append(MCPServerConfig.from_dict(name, srv_data))
                                    # Use print instead of logger to avoid circular import issues during config load
                                    print(f"Loaded MCP server '{name}' from {mcp_json_path}")
                except Exception as e:
                    print(f"Failed to load MCP servers from {mcp_json_path}: {e}")

            # Filter out stdio servers on Windows unless explicitly enabled
            if (
                platform.system() == "Windows"
                and not os.getenv("FORGE_ENABLE_WINDOWS_MCP")
            ):
                original_count = len(servers)
                # Allow npx/uvx-based servers even on Windows
                servers = [s for s in servers if s.type != "stdio" or s.name in ("browser-use", "context7", "shadcn", "github", "fetch", "duckduckgo", "magic", "rigour")]
                skipped = original_count - len(servers)
                if skipped > 0:
                    logger.info(
                        "Windows stdlib MCP disabled by default: filtered out %s stdio server(s); HTTP/SSE MCP remains enabled.",
                        skipped,
                    )

            mcp_config = cls(enabled=enabled, servers=servers)
            mcp_config.validate_servers()
            mcp_mapping["mcp"] = mcp_config
        except ValidationError as e:
            msg = f"Invalid MCP configuration: {e}"
            raise ValueError(msg) from e
        return mcp_mapping

    def merge(self, other: MCPConfig) -> MCPConfig:
        """Merge this config with another MCP config.

        Args:
            other: MCP config to merge

        Returns:
            New merged MCPConfig

        """
        return MCPConfig(
            enabled=self.enabled or other.enabled,
            servers=self.servers + other.servers,
        )

    # Backward compatibility: support old three-list format
    @property
    def sse_servers(self) -> list:
        """Backward compat: return SSE servers from unified list."""
        return [s for s in self.servers if s.type == "sse"]

    @property
    def stdio_servers(self) -> list:
        """Backward compat: return stdio servers from unified list."""
        return [s for s in self.servers if s.type == "stdio"]

    @property
    def shttp_servers(self) -> list:
        """Backward compat: return sHTTP servers from unified list."""
        return [s for s in self.servers if s.type == "shttp"]


class ForgeMCPConfig:
    """Utility class for creating default Forge MCP configurations."""

    @staticmethod
    def create_default_mcp_server_config(
        host: str,
        config: ForgeConfig,
        user_id: str | None = None,
    ) -> tuple[MCPServerConfig | None, list[MCPServerConfig]]:
        """Create a default MCP server configuration.

        Args:
            host: Host string
            config: ForgeConfig
            user_id: Optional user ID for the MCP server
        Returns:
            tuple[MCPServerConfig | None, list[MCPServerConfig]]:
                A tuple containing the default remote server configuration
                (or None) and a list of MCP stdio server configurations

        """
        stdio_servers: list[MCPServerConfig] = []
        shttp_servers = MCPServerConfig(
            name="forge-mcp", type="shttp", url=f"http://{host}/mcp/mcp", api_key=None
        )
        return (shttp_servers, stdio_servers)


FORGE_mcp_config_cls = os.environ.get(
    "FORGE_MCP_CONFIG_CLS",
    DEFAULT_FORGE_MCP_CONFIG_CLS,
)
ForgeMCPConfigImpl = get_impl(ForgeMCPConfig, FORGE_mcp_config_cls)

__all__ = [
    "MCPRemoteServerConfig",
    "MCPStdioServerConfig",
    "MCPConfig",
    "ForgeMCPConfig",
    "ForgeMCPConfigImpl",
]
