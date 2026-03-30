"""Configuration models for Model Context Protocol (MCP) servers and clients."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
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
from backend.core.constants import DEFAULT_APP_MCP_CONFIG_CLS
from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig
from backend.utils.import_utils import get_impl

# When set (1/true/yes), ``load_bundled_mcp_server_configs`` returns []. Unit tests that
# assert exact MCP server lists should set this env var; production leaves it unset.
NO_BUNDLED_MCP_DEFAULTS_ENV = "APP_NO_BUNDLED_MCP_DEFAULTS"


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
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname or hostname in {"none", "null"}:
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
        usage_hint: Optional one-line guidance for the agent system prompt (when to use this server).

    """

    name: str
    type: Literal["stdio", "sse", "shttp"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    api_key: str | None = None
    transport: Literal["sse", "shttp"] = "sse"
    usage_hint: str | None = Field(
        default=None,
        description=(
            "Short sentence injected into the agent system prompt under the MCP server name "
            "(e.g. when to prefer Context7 vs browser vs fetch)."
        ),
    )

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

    @field_validator("usage_hint", mode="before")
    @classmethod
    def strip_usage_hint(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        if len(s) > 800:
            return s[:800].rstrip()
        return s

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
            and self.usage_hint == other.usage_hint
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

    enabled: bool = True
    servers: list[MCPServerConfig] = Field(default_factory=list)
    #: Internal orchestrator tool names reserved when exposing MCP tools (runtime + API must match).
    mcp_exposed_name_reserved: frozenset[str] = Field(default_factory=frozenset)
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
        _known_keys = {"enabled", "servers"}
        unknown = set(data) - _known_keys
        if unknown:
            msg = f"Invalid MCP configuration: unknown keys: {', '.join(sorted(unknown))}"
            raise ValueError(msg)

        try:
            enabled = data.get("enabled", False)
            servers_data = data.get("servers", [])
            if isinstance(servers_data, dict):
                servers_data = [servers_data]
            servers = [MCPServerConfig(**s) for s in servers_data]
            extend_mcp_servers_with_bundled_defaults(servers)
            servers = _filter_windows_stdio_servers(servers)
            mcp_config = cls(enabled=enabled, servers=servers)
            mcp_config.validate_servers()
            return {"mcp": mcp_config}
        except ValidationError as e:
            raise ValueError(f"Invalid MCP configuration: {e}") from e

    def merge(self, other: MCPConfig) -> MCPConfig:
        """Merge this config with another MCP config."""
        return MCPConfig(
            enabled=self.enabled or other.enabled,
            servers=self.servers + other.servers,
            mcp_exposed_name_reserved=self.mcp_exposed_name_reserved
            | other.mcp_exposed_name_reserved,
        )

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


def _bundled_mcp_defaults_disabled() -> bool:
    v = (os.getenv(NO_BUNDLED_MCP_DEFAULTS_ENV) or "").strip().lower()
    return v in ("1", "true", "yes")


def _bundled_mcp_json_path() -> Path | None:
    """Location of packaged ``backend/runtime/mcp/config.json`` (single source for path)."""
    try:
        backend_root = Path(__file__).resolve().parent.parent.parent
        candidate = backend_root / "runtime" / "mcp" / "config.json"
        if candidate.is_file():
            return candidate
    except Exception:
        pass
    try:
        cwd_candidate = Path("backend") / "runtime" / "mcp" / "config.json"
        if cwd_candidate.is_file():
            return cwd_candidate.resolve()
    except Exception:
        pass
    return None


def load_bundled_mcp_server_configs() -> list[MCPServerConfig]:
    """Read default MCP servers from bundled ``config.json`` (single source of truth).

    Returns the bundled entries only, after the same Windows stdio policy as the rest
    of MCP config. Returns ``[]`` when disabled via :data:`NO_BUNDLED_MCP_DEFAULTS_ENV`,
    when the file is missing, or when JSON is invalid.
    """
    if _bundled_mcp_defaults_disabled():
        return []
    path = _bundled_mcp_json_path()
    if path is None:
        return []
    try:
        with path.open(encoding="utf-8") as f:
            mcp_json = json.load(f)
        srvs = mcp_json.get("mcpServers") or {}
        out: list[MCPServerConfig] = []
        for name, srv_data in srvs.items():
            if name == "default" or not isinstance(srv_data, dict):
                continue
            out.append(MCPServerConfig.from_dict(name, srv_data))
        return _filter_windows_stdio_servers(out)
    except Exception as e:
        logger.warning("Bundled MCP defaults not loaded from %s: %s", path, e)
        return []


def extend_mcp_servers_with_bundled_defaults(servers: list[MCPServerConfig]) -> None:
    """Append bundled defaults for any server name not already in ``servers`` (in place).

    Used by :meth:`MCPConfig.from_toml_section` and :func:`finalize_config` so there is
    one merge rule for the concept “add repo defaults without clobbering explicit config”.
    """
    existing = {s.name for s in servers}
    for srv in load_bundled_mcp_server_configs():
        if srv.name not in existing:
            servers.append(srv)
            existing.add(srv.name)
            logger.debug("Applied bundled MCP default server '%s'", srv.name)


def dedupe_default_mcp_http_servers(mcp: MCPConfig) -> None:
    """Keep a single ``app-mcp`` server row (first wins) after user merges."""
    seen = False
    kept: list[MCPServerConfig] = []
    for s in mcp.servers:
        if s.name == "app-mcp":
            if seen:
                continue
            seen = True
        kept.append(s)
    mcp.servers = kept


def ensure_default_mcp_http_server(cfg: Any) -> None:
    """Ensure the default SHTTP MCP server exists once (single source of truth)."""
    dedupe_default_mcp_http_servers(cfg.mcp)
    default, stdio_extra = AppMCPConfigImpl.create_default_mcp_server_config(
        cfg.mcp_host,
        cfg,
        None,
    )
    if default is None:
        return
    if any(s.name == "app-mcp" for s in cfg.mcp.servers):
        return
    if default.url and any(getattr(s, "url", None) == default.url for s in cfg.mcp.servers):
        return
    cfg.mcp.servers.append(default)
    if stdio_extra:
        cfg.mcp.servers.extend(stdio_extra)


def _filter_windows_stdio_servers(servers: list) -> list:
    """Return servers unconditionally (OS agnosticism)."""
    return servers


class AppMCPConfig:
    """Utility class for creating default application MCP configurations."""

    @staticmethod
    def create_default_mcp_server_config(
        host: str | None,
        config: AppConfig,
        user_id: str | None = None,
    ) -> tuple[MCPServerConfig | None, list[MCPServerConfig]]:
        """Create a default MCP server configuration.

        Args:
            host: Host string
            config: AppConfig
            user_id: Optional user ID for the MCP server
        Returns:
            tuple[MCPServerConfig | None, list[MCPServerConfig]]:
                A tuple containing the default remote server configuration
                (or None) and a list of MCP stdio server configurations

        """
        stdio_servers: list[MCPServerConfig] = []

        normalized_host = (host or "").strip()
        if not normalized_host or normalized_host.lower() in {"none", "null"}:
            logger.warning(
                "Skipping default MCP server: invalid mcp_host=%r", host
            )
            return (None, stdio_servers)

        shttp_servers = MCPServerConfig(
            name="app-mcp",
            type="shttp",
            url=f"http://{normalized_host}/mcp/mcp",
            api_key=None,
            transport="shttp",
        )
        return (shttp_servers, stdio_servers)


configured_mcp_config_cls = os.environ.get(
    "APP_MCP_CONFIG_CLS",
    DEFAULT_APP_MCP_CONFIG_CLS,
)
AppMCPConfigImpl = get_impl(AppMCPConfig, configured_mcp_config_cls)

__all__ = [
    "MCPRemoteServerConfig",
    "MCPStdioServerConfig",
    "MCPConfig",
    "AppMCPConfig",
    "AppMCPConfigImpl",
    "NO_BUNDLED_MCP_DEFAULTS_ENV",
    "dedupe_default_mcp_http_servers",
    "ensure_default_mcp_http_server",
    "extend_mcp_servers_with_bundled_defaults",
    "load_bundled_mcp_server_configs",
]
