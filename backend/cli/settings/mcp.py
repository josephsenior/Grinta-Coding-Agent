"""Settings — MCP server list in settings.json."""

from __future__ import annotations

import logging
import shlex
from typing import Any

from backend.cli.settings.storage import _load_raw_settings, _save_raw_settings
from backend.core.config import AppConfig

logger = logging.getLogger(__name__)


def _server_dict(
    name: str,
    *,
    server_type: str,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    entry: dict[str, Any] = {'name': name, 'type': server_type, 'enabled': enabled}
    if url:
        entry['url'] = url
    if command:
        entry['command'] = command
    if args:
        entry['args'] = args
    return entry


def _find_server_index(servers: list[dict[str, Any]], name: str) -> int | None:
    for index, server in enumerate(servers):
        if str(server.get('name') or '') == name:
            return index
    return None


def mcp_server_endpoint(server: dict[str, Any]) -> str:
    """Return a single-line command or URL for display/editing."""
    url = server.get('url')
    if url:
        return str(url)
    command = str(server.get('command') or '').strip()
    if not command:
        return ''
    args = server.get('args') or []
    if isinstance(args, list) and args:
        return shlex.join([command, *[str(arg) for arg in args]])
    return command


def get_mcp_servers(config: AppConfig) -> list[dict[str, Any]]:
    from backend.integrations.mcp.native_backends import (
        filter_user_visible_mcp_server_dicts,
    )

    try:
        if config.mcp and config.mcp.servers:
            return filter_user_visible_mcp_server_dicts(
                [
                    {
                        'name': s.name,
                        'type': s.type,
                        'url': getattr(s, 'url', None),
                        'command': getattr(s, 'command', None),
                        'args': list(getattr(s, 'args', None) or []),
                        'enabled': bool(getattr(s, 'enabled', True)),
                    }
                    for s in config.mcp.servers
                ]
            )
    except Exception:
        logger.debug('Could not read MCP server list', exc_info=True)
    return []


def get_mcp_server(config: AppConfig, name: str) -> dict[str, Any] | None:
    for server in get_mcp_servers(config):
        if str(server.get('name') or '') == name:
            return server
    return None


def add_mcp_server(
    name: str, *, url: str | None = None, command: str | None = None
) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config', {})
    servers = mcp_cfg.get('servers', [])

    entry: dict[str, Any]
    if url:
        entry = _server_dict(name, server_type='sse', url=url)
    elif command:
        parts = shlex.split(command)
        entry = _server_dict(
            name,
            server_type='stdio',
            command=parts[0],
            args=parts[1:],
        )
    else:
        raise ValueError('Specify either url or command')

    servers.append(entry)
    mcp_cfg['servers'] = servers
    settings['mcp_config'] = mcp_cfg
    _save_raw_settings(settings)


def update_mcp_server(
    name: str,
    *,
    url: str | None = None,
    command: str | None = None,
    enabled: bool | None = None,
    config: AppConfig | None = None,
) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config', {})
    servers = list(mcp_cfg.get('servers', []))
    index = _find_server_index(servers, name)
    if index is None:
        if config is None:
            raise ValueError(f"MCP server '{name}' not found")
        server = get_mcp_server(config, name)
        if server is None:
            raise ValueError(f"MCP server '{name}' not found")
        current = dict(server)
    else:
        current = dict(servers[index])

    if enabled is not None:
        current['enabled'] = enabled
    if url is not None:
        current['type'] = 'sse'
        current['url'] = url
        current.pop('command', None)
        current.pop('args', None)
    elif command is not None:
        parts = shlex.split(command)
        current['type'] = 'stdio'
        current['command'] = parts[0]
        current['args'] = parts[1:]
        current.pop('url', None)

    if index is None:
        servers.append(current)
    else:
        servers[index] = current
    mcp_cfg['servers'] = servers
    settings['mcp_config'] = mcp_cfg
    _save_raw_settings(settings)


def set_mcp_master_enabled(enabled: bool) -> None:
    """Enable or disable the MCP integration globally (``mcp_config.enabled``)."""
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config')
    if not isinstance(mcp_cfg, dict):
        mcp_cfg = {}
    mcp_cfg['enabled'] = bool(enabled)
    settings['mcp_config'] = mcp_cfg
    _save_raw_settings(settings)


def set_mcp_server_enabled(
    name: str, enabled: bool, *, config: AppConfig | None = None
) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config', {})
    servers = list(mcp_cfg.get('servers', []))
    index = _find_server_index(servers, name)
    if index is None:
        if config is None:
            raise ValueError(f"MCP server '{name}' not found")
        server = get_mcp_server(config, name)
        if server is None:
            raise ValueError(f"MCP server '{name}' not found")
        entry = {
            'name': server['name'],
            'type': server['type'],
            'enabled': enabled,
        }
        if server.get('url'):
            entry['url'] = server['url']
        if server.get('command'):
            entry['command'] = server['command']
        if server.get('args'):
            entry['args'] = server['args']
        servers.append(entry)
    else:
        servers[index] = {**servers[index], 'enabled': enabled}
    mcp_cfg['servers'] = servers
    settings['mcp_config'] = mcp_cfg
    _save_raw_settings(settings)


def remove_mcp_server(name: str) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config', {})
    servers = mcp_cfg.get('servers', [])

    new_servers = [s for s in servers if s.get('name') != name]
    if len(new_servers) == len(servers):
        raise ValueError(f"MCP server '{name}' not found")

    mcp_cfg['servers'] = new_servers
    settings['mcp_config'] = mcp_cfg
    _save_raw_settings(settings)
