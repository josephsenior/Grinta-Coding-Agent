"""Settings — JSON file I/O."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console

from backend.cli.theme import (
    no_color_enabled,
)
from backend.core.app_paths import get_app_settings_root

logger = logging.getLogger(__name__)
_console = Console(no_color=no_color_enabled())

from backend.cli.settings.constants import *  # noqa: F403


def _settings_path() -> Path:
    """Resolve canonical settings path anchored to repository root."""
    return Path(get_app_settings_root()) / 'settings.json'


def _load_raw_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        settings = json.load(f)
    legacy_reasoning = settings.pop('reasoningEffort', None)
    if legacy_reasoning is not None and 'llm_reasoning_effort' not in settings:
        settings['llm_reasoning_effort'] = legacy_reasoning
    return settings


def _normalize_mcp_server_rows(mcp_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a deep-copied list of server dicts (drops the legacy ``default`` key)."""
    raw_servers = mcp_cfg.get('servers', [])
    if isinstance(raw_servers, dict):
        raw_servers = [raw_servers]
    if not isinstance(raw_servers, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw_servers:
        if not isinstance(row, dict):
            continue
        name = row.get('name')
        if not name or name == 'default':
            continue
        out.append(dict(row))
    return out


def _settings_mcp_signature(data: dict[str, Any]) -> tuple:
    """Stable hashable signature of the ``mcp_config.servers`` slice.

    Used to detect whether the on-disk change actually affected MCP
    servers before we wake up the bus and force a runtime reconnect.
    Order matters: editing a server's args while leaving its position
    intact must still register as a change.
    """
    mcp_cfg = data.get('mcp_config') or {}
    if not isinstance(mcp_cfg, dict):
        return ((), False, ())
    servers = _normalize_mcp_server_rows(mcp_cfg)
    sig_servers: list[tuple] = []
    for row in servers:
        sig_servers.append(
            (
                row.get('name'),
                row.get('type'),
                row.get('url'),
                row.get('command'),
                tuple(row.get('args') or ()),
                tuple(sorted((row.get('env') or {}).items())),
                row.get('api_key'),
                row.get('transport'),
                row.get('usage_hint'),
                bool(row.get('enabled', True)),
            )
        )
    return (
        tuple(sig_servers),
        bool(mcp_cfg.get('enabled', True)),
        tuple(sorted(mcp_cfg.get('mcp_exposed_name_reserved', []) or ())),
    )


def _save_raw_settings(data: dict[str, Any], *, source: str = 'mutation') -> None:
    """Persist ``data`` to ``settings.json`` and notify the MCP bus on change.

    Args:
        data: Full settings dict to serialize.
        source: Origin tag for the bus event. ``"mutation"`` is the
            default for in-process mutators; the file watcher calls
            this with ``"file_watch"`` so subscribers can suppress
            feedback loops.
    """
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    prev_signature = None
    try:
        if path.exists():
            prev_signature = _settings_mcp_signature(_load_raw_settings())
    except Exception:
        prev_signature = None

    # Mark this write as our own so the background file watcher does
    # not re-emit it as a ``file_watch`` event (would loop). Safe no-op
    # when no watcher is running.
    try:
        from backend.cli.tui.services.settings_watcher import (
            stamp_self_write as _stamp,
        )

        _stamp()
    except Exception:
        pass

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    new_signature = _settings_mcp_signature(data)
    if new_signature == prev_signature:
        return

    try:
        from backend.core.config.config_loader import load_mcp_config_from_json
        from backend.integrations.mcp.config_bus import get_mcp_config_bus

        new_config = load_mcp_config_from_json(_settings_path())
        get_mcp_config_bus().emit(new_config, source=source)
    except Exception as exc:
        logger.debug('MCPConfigBus emit skipped: %s', exc, exc_info=True)


def _server_dict_to_config(*, name: str, row: dict[str, Any]) -> Any:
    """Coerce a raw settings dict into a :class:`MCPServerConfig`."""
    from backend.core.config.mcp_config import MCPServerConfig

    payload = dict(row)
    payload['name'] = name
    payload.setdefault('type', 'stdio' if payload.get('command') else 'sse')
    return MCPServerConfig(**payload)
