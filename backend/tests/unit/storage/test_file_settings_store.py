"""Tests for backend.storage.settings.file_settings_store.FileSettingsStore."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.storage.settings.file_settings_store import (
    FileSettingsStore,
    _file_settings_cache,
    _file_settings_locks,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear global caches before each test."""
    _file_settings_cache.clear()
    _file_settings_locks.clear()
    yield
    _file_settings_cache.clear()
    _file_settings_locks.clear()


# ── __init__ ──────────────────────────────────────────────────────────


class TestFileSettingsStoreInit:
    def test_default_path(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)
        assert store.path == "settings.json"
        assert store.file_store is fs

    def test_custom_path(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs, path="custom/settings.json")
        assert store.path == "custom/settings.json"


# ── load ──────────────────────────────────────────────────────────────


class TestFileSettingsStoreLoad:
    async def test_load_returns_none_when_file_not_found(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)

        with patch(
            "backend.storage.settings.file_settings_store.call_sync_from_async",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ):
            result = await store.load()
            assert result is None

    async def test_load_returns_settings_from_json(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)

        data = json.dumps({"language": "python", "agent": "Orchestrator"})

        with patch(
            "backend.storage.settings.file_settings_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await store.load()
            assert result is not None

    async def test_load_caches_result(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)
        data = json.dumps({"language": "python"})

        with patch(
            "backend.storage.settings.file_settings_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ) as mock_read:
            # First call — reads from file
            r1 = await store.load()
            # Second call — should hit cache
            r2 = await store.load()
            # Only one file read should happen
            assert mock_read.await_count == 1
            assert r1 is r2

    async def test_load_caches_none_result(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)

        with patch(
            "backend.storage.settings.file_settings_store.call_sync_from_async",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError,
        ) as mock_read:
            r1 = await store.load()
            r2 = await store.load()
            assert r1 is None
            assert r2 is None
            assert mock_read.await_count == 1

    async def test_cache_expires_after_ttl(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)
        data = json.dumps({"language": "python"})

        with patch(
            "backend.storage.settings.file_settings_store.call_sync_from_async",
            new_callable=AsyncMock,
            return_value=data,
        ) as mock_read:
            await store.load()
            # Manually expire the cache entry
            key = store.path
            if key in _file_settings_cache:
                settings, _ = _file_settings_cache[key]
                _file_settings_cache[key] = (settings, time.time() - 9999)

            await store.load()
            assert mock_read.await_count == 2


# ── store ─────────────────────────────────────────────────────────────


class TestFileSettingsStoreStore:
    async def test_store_writes_and_invalidates_cache(self):
        fs = MagicMock()
        store = FileSettingsStore(file_store=fs)

        # Pre-populate cache
        _file_settings_cache[store.path] = (MagicMock(), time.time())

        mock_settings = MagicMock()

        with (
            patch(
                "backend.storage.settings.file_settings_store.model_dump_json",
                return_value='{"language": "python"}',
            ),
            patch(
                "backend.storage.settings.file_settings_store.call_sync_from_async",
                new_callable=AsyncMock,
            ) as mock_write,
        ):
            await store.store(mock_settings)
            mock_write.assert_awaited_once()
            # Cache should be cleared
            assert store.path not in _file_settings_cache


# ── get_instance ──────────────────────────────────────────────────────


class TestFileSettingsStoreGetInstance:
    async def test_creates_instance(self):
        mock_config = MagicMock()
        mock_config.file_store = "local"
        mock_config.file_store_path = "/tmp/test"
        mock_config.file_store_web_hook_url = None
        mock_config.file_store_web_hook_headers = None
        mock_config.file_store_web_hook_batch = False

        with patch(
            "backend.storage.settings.file_settings_store.get_file_store",
            return_value=MagicMock(),
        ):
            instance = await FileSettingsStore.get_instance(mock_config, "user-1")
            assert isinstance(instance, FileSettingsStore)
