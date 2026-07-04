"""File watcher for ``settings.json`` that wakes the MCP config bus.

The watcher runs as an ``asyncio`` task. It polls ``settings.json``
``mtime`` at a low frequency and emits a :class:`MCPConfigChange` to
the bus on change. We deliberately avoid the third-party ``watchdog``
package so this works in the same dependency-light fashion as the rest
of Grinta and runs identically on Windows, macOS, and Linux.

The watcher keeps a *mtime* + *size* signature and re-reads the file
in a thread to avoid blocking the loop on JSON parse. It also dedups
writes done by Grinta itself: every time the in-process mutator saves
the file, it stamps :data:`stamp_self_write` so the next tick of the
watcher can drop that write rather than re-emit a redundant event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _FileFingerprint:
    """Cached on-disk state used to detect external edits."""

    mtime_ns: int
    size: int

    def matches(self, other: _FileFingerprint) -> bool:
        return self.mtime_ns == other.mtime_ns and self.size == other.size


def _fingerprint_from_stat(st: os.stat_result) -> _FileFingerprint:
    return _FileFingerprint(mtime_ns=st.st_mtime_ns, size=st.st_size)


# Process-singleton self-write stamp. Any in-process save (the CLI
# settings mutators, the manage dialog, the tests) can call
# :func:`stamp_self_write` to mark the *next* observed write as our
# own. The active watcher reads this via :func:`consume_self_write` to
# drop the resulting mtime update before re-emitting the same config
# we just persisted (which would loop the bus into a thundering
# reconnect).
_SELF_WRITE_TTL_SEC = 2.0
_self_write_lock = threading.Lock()
_last_self_write: float = 0.0


def stamp_self_write() -> None:
    """Mark the next on-disk write we observe as our own.

    Callers (e.g. :func:`backend.cli.settings.storage._save_raw_settings`)
    should call this **before** the atomic rename so the watcher's
    next poll recognises the resulting mtime as ours and skips the
    emit. Safe to call when no watcher is running.
    """
    global _last_self_write
    with _self_write_lock:
        _last_self_write = time.monotonic()


def consume_self_write() -> bool:
    """Return True when the most recent on-disk write was stamped by us.

    Called by the watcher once per tick to suppress feedback loops.
    """
    global _last_self_write
    with _self_write_lock:
        stamp = _last_self_write
        if stamp == 0.0:
            return False
        if (time.monotonic() - stamp) >= _SELF_WRITE_TTL_SEC:
            return False
        _last_self_write = 0.0
        return True


class SettingsFileWatcher:
    """Poll ``settings.json`` and emit MCP config changes.

    Lifecycle::

        watcher = SettingsFileWatcher(settings_path)
        watcher.install()           # sets baseline fingerprint
        await watcher.start()       # spawns the background poll task
        ...
        await watcher.stop()        # cancels the task
    """

    POLL_INTERVAL_SEC = 1.0

    def __init__(self, settings_path: Path) -> None:
        self._path = Path(settings_path)
        self._task: asyncio.Task[None] | None = None
        self._baseline: _FileFingerprint | None = None
        self._stopping = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def install(self) -> None:
        """Capture the current file state as the baseline."""
        try:
            st = self._path.stat()
        except FileNotFoundError:
            self._baseline = None
            return
        except OSError as exc:
            logger.debug('SettingsFileWatcher install stat failed: %s', exc)
            self._baseline = None
            return
        self._baseline = _fingerprint_from_stat(st)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name='grinta-settings-watcher')

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug('SettingsFileWatcher stop: %s', exc, exc_info=True)
        self._task = None

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        try:
            while not self._stopping:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug(
                        'SettingsFileWatcher tick raised: %s', exc, exc_info=True
                    )
                await asyncio.sleep(self.POLL_INTERVAL_SEC)
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> None:
        try:
            current_stat = await asyncio.to_thread(self._safe_stat)
        except Exception as exc:
            logger.debug('SettingsFileWatcher stat error: %s', exc)
            return
        if current_stat is None:
            if self._baseline is not None:
                self._baseline = None
                await self._emit_removal()
            return

        fingerprint = _fingerprint_from_stat(current_stat)
        if self._baseline is None:
            self._baseline = fingerprint
            return
        if self._baseline.matches(fingerprint):
            return
        if consume_self_write():
            self._baseline = fingerprint
            return

        try:
            data = await asyncio.to_thread(self._safe_read)
        except Exception as exc:
            logger.debug('SettingsFileWatcher read error: %s', exc)
            return
        self._baseline = fingerprint
        if data is None:
            return
        await self._emit_external(data)

    @staticmethod
    def _safe_stat() -> os.stat_result | None:
        from backend.cli.settings.storage import _settings_path

        path = Path(_settings_path())
        try:
            return path.stat()
        except FileNotFoundError:
            return None
        except OSError:
            return None

    @staticmethod
    def _safe_read() -> dict[str, Any] | None:
        from backend.cli.settings.storage import _load_raw_settings

        try:
            return _load_raw_settings()
        except (json.JSONDecodeError, OSError):
            return None

    async def _emit_external(self, data: dict[str, Any]) -> None:
        from backend.core.config.mcp_config import MCPConfig, MCPServerConfig
        from backend.integrations.mcp.config_bus import get_mcp_config_bus

        mcp_cfg = data.get('mcp_config') or {}
        if not isinstance(mcp_cfg, dict):
            return
        raw_servers = mcp_cfg.get('servers', [])
        if isinstance(raw_servers, dict):
            raw_servers = [raw_servers]
        servers: list[MCPServerConfig] = []
        for row in raw_servers or []:
            if not isinstance(row, dict):
                continue
            name = row.get('name')
            if not name or name == 'default':
                continue
            try:
                servers.append(MCPServerConfig(**{**row, 'name': name}))
            except Exception as exc:
                logger.warning(
                    'SettingsFileWatcher: dropped invalid server %r: %s',
                    name,
                    exc,
                )

        new_config = MCPConfig(
            enabled=bool(mcp_cfg.get('enabled', True)),
            servers=servers,
            mcp_exposed_name_reserved=frozenset(
                mcp_cfg.get('mcp_exposed_name_reserved', []) or []
            ),
        )
        async with self._lock:
            get_mcp_config_bus().emit(new_config, source='file_watch')

    async def _emit_removal(self) -> None:
        from backend.core.config.mcp_config import MCPConfig
        from backend.integrations.mcp.config_bus import get_mcp_config_bus

        async with self._lock:
            get_mcp_config_bus().emit(
                MCPConfig(enabled=False, servers=[]),
                source='file_watch',
            )


__all__ = ['SettingsFileWatcher', 'stamp_self_write', 'consume_self_write']
