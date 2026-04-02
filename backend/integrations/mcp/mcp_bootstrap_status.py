"""Structured MCP bootstrap / capability state (machine-readable, not inferred from empty tool lists)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MCPBootstrapState = Literal[
    'unknown',
    'mcp_disabled',
    'no_servers_configured',
    'fetch_failed',
    'no_clients_connected',
    'connected_no_remote_tools',
    'healthy',
    'partial_tool_conversion',
]

_last_status: 'MCPBootstrapStatus | None' = None


@dataclass
class MCPBootstrapStatus:
    """Snapshot of the most recent MCP tool discovery attempt for this process."""

    state: MCPBootstrapState = 'unknown'
    mcp_enabled: bool = False
    configured_server_count: int = 0
    attempted_server_count: int = 0
    connected_client_count: int = 0
    remote_tool_param_count: int = 0
    conversion_errors: list[str] = field(default_factory=list)
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'state': self.state,
            'mcp_enabled': self.mcp_enabled,
            'configured_server_count': self.configured_server_count,
            'attempted_server_count': self.attempted_server_count,
            'connected_client_count': self.connected_client_count,
            'remote_tool_param_count': self.remote_tool_param_count,
            'conversion_errors': list(self.conversion_errors),
            'last_error': self.last_error,
        }


def get_mcp_bootstrap_status() -> dict[str, Any]:
    """Return the last recorded MCP bootstrap status, or a neutral default."""
    if _last_status is None:
        return MCPBootstrapStatus().as_dict()
    return _last_status.as_dict()


def set_mcp_bootstrap_status(status: MCPBootstrapStatus) -> None:
    """Record MCP bootstrap outcome (called from fetch / conversion paths)."""
    global _last_status
    _last_status = status


def reset_mcp_bootstrap_status() -> None:
    """Clear stored status (mainly for tests)."""
    global _last_status
    _last_status = None
