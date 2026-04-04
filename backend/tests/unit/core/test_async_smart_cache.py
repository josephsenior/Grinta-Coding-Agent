"""Tests for backend.core.cache.async_smart_cache."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.core.cache.async_smart_cache as mod


@pytest.fixture
def cache():
    return mod.AsyncSmartCache()


class TestAsyncSmartCache:
    @pytest.mark.asyncio
    async def test_ensure_connection_returns_false(self, cache):
        assert await cache._ensure_connection() is False
        assert cache.redis_available is False

    @pytest.mark.asyncio
    @patch('backend.core.config.config_loader.load_app_config')
    async def test_get_global_config_memory_miss(self, mock_load, cache):
        fake_config = MagicMock()
        mock_load.return_value = fake_config

        result = await cache.get_global_config()

        assert result is fake_config
        assert cache._global_config_cache is fake_config

    @pytest.mark.asyncio
    @patch('backend.core.config.config_loader.load_app_config')
    async def test_get_global_config_memory_hit(self, mock_load, cache):
        fake_config = MagicMock()
        cache._global_config_cache = fake_config
        cache._global_config_time = time.time()

        result = await cache.get_global_config()

        assert result is fake_config
        mock_load.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_settings_memory_hit(self, cache):
        fake_settings = MagicMock()
        cache._user_settings_cache['u1'] = (fake_settings, time.time())
        store = AsyncMock()

        result = await cache.get_user_settings('u1', store)

        assert result is fake_settings
        store.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_settings_memory_miss(self, cache):
        loaded = MagicMock()
        store = AsyncMock()
        store.load.return_value = loaded

        with patch(
            'backend.core.config.config_loader.load_app_config',
            return_value=MagicMock(),
        ):
            with patch(
                'backend.core.cache.async_smart_cache.merge_settings_with_cache',
                return_value=loaded,
            ):
                result = await cache.get_user_settings('u1', store)

        assert result is loaded
        store.load.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user_settings_returns_none(self, cache):
        store = AsyncMock()
        store.load.return_value = None

        result = await cache.get_user_settings('u1', store)

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_user_cache(self, cache):
        cache._user_settings_cache['u1'] = (MagicMock(), time.time())

        await cache.invalidate_user_cache('u1')

        assert 'u1' not in cache._user_settings_cache

    @pytest.mark.asyncio
    async def test_invalidate_global_cache(self, cache):
        cache._global_config_cache = MagicMock()
        cache._global_config_time = time.time()

        await cache.invalidate_global_cache()

        assert cache._global_config_cache is None
        assert cache._global_config_time == 0

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, cache):
        stats = await cache.get_cache_stats()

        assert stats['cache_type'] == 'memory'
        assert stats['redis_available'] is False
        assert stats['global_config_cached'] is False
        assert stats['cached_users'] == 0

    @pytest.mark.asyncio
    async def test_close_clears_client_reference(self, cache):
        cache.redis_client = object()

        await cache.close()

        assert cache.redis_client is None


class TestAsyncSmartCacheSingleton:
    @pytest.mark.asyncio
    async def test_get_async_smart_cache(self):
        mod._async_smart_cache = None

        instance = await mod.get_async_smart_cache()

        assert isinstance(instance, mod.AsyncSmartCache)
        assert await mod.get_async_smart_cache() is instance
        mod._async_smart_cache = None
