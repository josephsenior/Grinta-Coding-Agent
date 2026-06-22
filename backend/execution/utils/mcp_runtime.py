"""Shared MCP client lifecycle for runtime implementations."""

from __future__ import annotations

from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.ledger.observation import ErrorObservation, Observation


async def call_mcp_action(
    action: Any,
    *,
    mcp_config: Any | None,
    clients: list[Any] | None,
    servers_resolved: list[Any] | None,
) -> tuple[Observation, list[Any] | None, list[Any] | None]:
    """Execute an MCP tool call using the shared Grinta MCP integration.

    Returns:
        ``(observation, updated_clients, updated_servers_resolved)``
    """
    try:
        from backend.core.config.config_loader import load_app_config
        from backend.core.config.mcp_config import _filter_windows_stdio_servers
        from backend.execution.aes.file_operations import (
            get_max_edit_observation_chars,
            truncate_large_text,
        )
        from backend.integrations.mcp.mcp_utils import call_tool_mcp, create_mcps

        cfg = mcp_config
        if cfg is None:
            cfg = load_app_config().mcp

        active_clients = clients
        active_servers = servers_resolved
        if active_clients is None:
            servers = list(getattr(cfg, 'servers', []) or [])
            servers = _filter_windows_stdio_servers(servers)
            active_servers = list(servers)
            active_clients = await create_mcps(servers)
            from backend.integrations.mcp.mcp_tool_aliases import (
                prepare_mcp_tool_exposed_names,
            )

            reserved = getattr(cfg, 'mcp_exposed_name_reserved', None) or frozenset()
            prepare_mcp_tool_exposed_names(active_clients, set(reserved))

        observation = await call_tool_mcp(
            active_clients,
            action,
            configured_servers=active_servers,
        )

        if hasattr(observation, 'content') and isinstance(observation.content, str):
            max_chars = get_max_edit_observation_chars()
            observation.content = truncate_large_text(
                observation.content, max_chars, label=f'MCP:{action.name}'
            )

        return observation, active_clients, active_servers
    except Exception as exc:
        logger.error(
            'MCP call failed for %s: %s',
            getattr(action, 'name', '?'),
            exc,
            exc_info=True,
        )
        return (
            ErrorObservation(
                content=(
                    f"MCP tool call failed for '{getattr(action, 'name', '?')}': "
                    f'{type(exc).__name__}: {exc}. '
                    'Use non-MCP tools as a fallback or check MCP configuration.'
                )
            ),
            clients,
            servers_resolved,
        )
