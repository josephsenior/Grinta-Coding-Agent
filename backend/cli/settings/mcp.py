"""Settings — MCP server list in settings.json."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.config import AppConfig
from backend.cli.settings.storage import _load_raw_settings, _save_raw_settings

logger = logging.getLogger(__name__)
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
                    }
                    for s in config.mcp.servers
                ]
            )
    except Exception:
        logger.debug('Could not read MCP server list', exc_info=True)
    return []


def add_mcp_server(
    name: str, *, url: str | None = None, command: str | None = None
) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get('mcp_config', {})
    servers = mcp_cfg.get('servers', [])

    entry: dict[str, Any] = {'name': name}
    if url:
        entry['type'] = 'sse'
        entry['url'] = url
    elif command:
        import shlex

        parts = shlex.split(command)
        entry['type'] = 'stdio'
        entry['command'] = parts[0]
        entry['args'] = parts[1:]
    else:
        raise ValueError('Specify either url or command')

    servers.append(entry)
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
