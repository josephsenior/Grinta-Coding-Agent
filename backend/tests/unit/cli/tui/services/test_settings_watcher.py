"""Unit tests for the ``settings.json`` file watcher.

Focus areas
-----------
* The watcher detects external edits and emits an :class:`MCPConfigChange`
  with ``source="file_watch"``.
* Writes stamped by the in-process mutator are *not* re-emitted
  (loop guard).
* Removing the file while the watcher is running emits a
  *disabled / empty* config so the runtime tears down every client.
* Subscribers raising exceptions do not break the watcher loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from backend.cli.tui.services.settings_watcher import (
    SettingsFileWatcher,
    consume_self_write,
    stamp_self_write,
)
from backend.integrations.mcp.config_bus import (
    get_mcp_config_bus,
    reset_mcp_config_bus,
)


@pytest.fixture(autouse=True)
def _reset() -> Any:
    reset_mcp_config_bus()
    yield
    reset_mcp_config_bus()


def _write_settings(path: Path, *, mcp: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        'mcp_config': {
            'enabled': True,
            'servers': mcp or [],
        }
    }
    path.write_text(json.dumps(payload), encoding='utf-8')


@pytest.mark.asyncio
async def test_external_edit_emits_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    _write_settings(settings_path)

    # Redirect the storage helpers used by the watcher.
    from backend.cli.settings import storage as storage_mod

    monkeypatch.setattr(storage_mod, '_settings_path', lambda: settings_path)
    monkeypatch.setattr(
        storage_mod, '_load_raw_settings', lambda: json.loads(settings_path.read_text())
    )

    watcher = SettingsFileWatcher(settings_path)
    watcher.POLL_INTERVAL_SEC = 0.05
    watcher.install()

    captured: list[Any] = []
    get_mcp_config_bus().subscribe(lambda c: captured.append(c))

    await watcher.start()
    try:
        # Wait for baseline to install, then mutate externally.
        await asyncio.sleep(0.1)
        _write_settings(
            settings_path,
            mcp=[{'name': 'github', 'type': 'stdio', 'command': 'gh', 'args': []}],
        )
        # Poll several times to give the watcher a chance to pick it up.
        for _ in range(20):
            if captured:
                break
            await asyncio.sleep(0.05)
        assert captured, 'watcher never emitted after external edit'
        assert captured[-1].source == 'file_watch'
        assert [s.name for s in captured[-1].diff.added] == ['github']
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_self_write_does_not_emit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    _write_settings(settings_path)

    from backend.cli.settings import storage as storage_mod

    monkeypatch.setattr(storage_mod, '_settings_path', lambda: settings_path)
    monkeypatch.setattr(
        storage_mod, '_load_raw_settings', lambda: json.loads(settings_path.read_text())
    )

    watcher = SettingsFileWatcher(settings_path)
    watcher.POLL_INTERVAL_SEC = 0.05
    watcher.install()

    captured: list[Any] = []
    get_mcp_config_bus().subscribe(lambda c: captured.append(c))

    await watcher.start()
    try:
        await asyncio.sleep(0.05)
        # Simulate the in-process mutator: stamp first, then write.
        stamp_self_write()
        _write_settings(
            settings_path,
            mcp=[{'name': 'local', 'type': 'stdio', 'command': 'foo'}],
        )
        for _ in range(20):
            await asyncio.sleep(0.05)
        assert captured == [], f'self-write should be suppressed, got {captured}'
    finally:
        await watcher.stop()


def test_stamp_consume_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reset any prior state from other tests in the same process.
    stamp_self_write()
    assert consume_self_write() is True
    assert consume_self_write() is False


@pytest.mark.asyncio
async def test_subscriber_exception_does_not_kill_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / 'settings.json'
    _write_settings(settings_path)
    from backend.cli.settings import storage as storage_mod

    monkeypatch.setattr(storage_mod, '_settings_path', lambda: settings_path)
    monkeypatch.setattr(
        storage_mod, '_load_raw_settings', lambda: json.loads(settings_path.read_text())
    )

    captured: list[Any] = []
    get_mcp_config_bus().subscribe(lambda c: (_ for _ in ()).throw(RuntimeError('x')))
    get_mcp_config_bus().subscribe(lambda c: captured.append(c))

    watcher = SettingsFileWatcher(settings_path)
    watcher.POLL_INTERVAL_SEC = 0.05
    watcher.install()
    await watcher.start()
    try:
        await asyncio.sleep(0.05)
        _write_settings(
            settings_path,
            mcp=[{'name': 'x', 'type': 'stdio', 'command': 'x'}],
        )
        for _ in range(20):
            if captured:
                break
            await asyncio.sleep(0.05)
        assert captured
    finally:
        await watcher.stop()
