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


async def reload_mcp_servers(
    *,
    new_servers: list[Any],
    current_clients: list[Any] | None,
    current_servers_resolved: list[Any] | None,
    reserved_tool_names: frozenset[str] | None = None,
) -> tuple[list[Any] | None, list[Any] | None, dict[str, list[str]]]:
    """Reconcile live MCP clients against a new server list.

    Diffs the existing client pool against ``new_servers`` (by
    ``(name, type)`` identity) and:

    * Disconnects + drops clients whose server was removed or whose
      editable fields changed (args/env/url/api_key/transport/usage_hint).
    * Keeps clients whose server is unchanged and re-applies the alias
      pass so freshly-added peers do not collide with existing exposed
      tool names.
    * Connects only the servers that were added or whose editable fields
      changed, in parallel via :func:`create_mcps`.

    The function never raises on partial failure: a server that fails
    to connect is simply absent from the returned client list. A
    structured summary of what happened is returned for the caller to
    surface in the TUI (added/removed/reconnected/failed names).

    Returns:
        ``(clients, servers_resolved, summary)`` where ``summary`` is a
        dict with keys ``added``, ``removed``, ``reconnected``,
        ``unchanged``, ``failed`` (each a list of server names).
    """
    from backend.core.config.mcp_config import _filter_windows_stdio_servers
    from backend.integrations.mcp.mcp_tool_aliases import (
        prepare_mcp_tool_exposed_names,
    )
    from backend.integrations.mcp.mcp_utils import create_mcps

    filtered_new = _filter_windows_stdio_servers(list(new_servers or []))
    filtered_old = _filter_windows_stdio_servers(list(current_servers_resolved or []))

    def _is_active(server: Any) -> bool:
        return bool(getattr(server, 'enabled', True))

    active_new = [s for s in filtered_new if _is_active(s)]
    active_old = [s for s in filtered_old if _is_active(s)]

    def _identity(server: Any) -> tuple[str, str]:
        return (getattr(server, 'name', ''), getattr(server, 'type', ''))

    old_by_id: dict[tuple[str, str], Any] = {_identity(s): s for s in active_old}
    new_by_id: dict[tuple[str, str], Any] = {_identity(s): s for s in active_new}

    added_ids = set(new_by_id) - set(old_by_id)
    removed_ids = set(old_by_id) - set(new_by_id)
    shared_ids = set(old_by_id) & set(new_by_id)

    kept_clients: list[Any] = []
    kept_servers: list[Any] = []
    reconnect_targets: list[Any] = []
    reconnect_ids: set[tuple[str, str]] = set()
    unchanged_names: list[str] = []
    reconnect_names: list[str] = []

    existing_clients = list(current_clients or [])
    for client in existing_clients:
        cfg = getattr(client, '_server_config', None)
        if cfg is None:
            try:
                await client.disconnect()
            except Exception as exc:
                logger.debug('MCP reload: failed to disconnect unknown client: %s', exc)
            continue
        ident = _identity(cfg)
        if ident in removed_ids:
            try:
                await client.disconnect()
            except Exception as exc:
                logger.debug(
                    'MCP reload: disconnect removed server %s: %s',
                    cfg.name,
                    exc,
                )
            continue
        if ident in shared_ids:
            new_cfg = new_by_id[ident]
            if cfg == new_cfg:
                kept_clients.append(client)
                kept_servers.append(new_cfg)
                unchanged_names.append(new_cfg.name)
                continue
            try:
                await client.disconnect()
            except Exception as exc:
                logger.debug(
                    'MCP reload: disconnect changed server %s: %s',
                    cfg.name,
                    exc,
                )
            reconnect_targets.append(new_cfg)
            reconnect_ids.add(ident)
        else:
            # Server identity is not in the new pool at all (no overlap
            # with ``shared_ids`` or ``removed_ids`` means the client's
            # server was renamed in-place). Drop the client to keep the
            # pool clean.
            try:
                await client.disconnect()
            except Exception as exc:
                logger.debug(
                    'MCP reload: disconnect stale client %s: %s',
                    cfg.name,
                    exc,
                )

    added_targets = [new_by_id[k] for k in sorted(added_ids)]
    connect_targets = added_targets + reconnect_targets

    new_clients: list[Any] = []
    failed_names: list[str] = []
    if connect_targets:
        try:
            new_clients = await create_mcps(connect_targets)
        except Exception as exc:
            logger.error('MCP reload: create_mcps raised: %s', exc, exc_info=True)
            new_clients = []

        connected_by_id: dict[tuple[str, str], Any] = {}
        for client in new_clients:
            cfg = getattr(client, '_server_config', None)
            if cfg is not None:
                connected_by_id[_identity(cfg)] = client

        for target in connect_targets:
            ident = _identity(target)
            client = connected_by_id.get(ident)
            if client is None:
                failed_names.append(target.name)
                continue
            if ident in reconnect_ids:
                reconnect_names.append(target.name)
            kept_clients.append(client)
            kept_servers.append(target)
    else:
        new_clients = []

    if reserved_tool_names is not None and kept_clients:
        try:
            prepare_mcp_tool_exposed_names(kept_clients, set(reserved_tool_names))
        except Exception as exc:
            logger.debug('MCP reload: alias preparation failed: %s', exc, exc_info=True)

    summary = {
        'added': [new_by_id[k].name for k in sorted(added_ids)],
        'removed': [old_by_id[k].name for k in sorted(removed_ids)],
        'reconnected': reconnect_names,
        'unchanged': unchanged_names,
        'failed': failed_names,
    }
    return kept_clients, kept_servers, summary


__all__ = ['call_mcp_action', 'reload_mcp_servers']
