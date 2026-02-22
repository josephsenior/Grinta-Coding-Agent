"""Tests for backend.core.cache.async_smart_cache — memory fallback path."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── AsyncSmartCache (memory fallback) ─────────────────────────────────


class TestAsyncSmartCacheMemory:
    @pytest.fixture
    def cache(self):
        with patch.dict("sys.modules", {"redis.asyncio": None, "redis": None}):
            import importlib
            import backend.core.cache.async_smart_cache as _mod

            importlib.reload(_mod)
            c = _mod.AsyncSmartCache()
            c.redis_available = False
            c.redis_client = None
            return c

    @pytest.mark.asyncio
    async def test_ensure_connection_returns_false_without_redis(self, cache):
        result = await cache._ensure_connection()
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.core.config.utils.load_forge_config")
    async def test_get_global_config_memory_miss(self, mock_load, cache):
        fake_config = MagicMock()
        mock_load.return_value = fake_config
        result = await cache.get_global_config()
        assert result is fake_config
        assert cache._global_config_cache is fake_config

    @pytest.mark.asyncio
    @patch("backend.core.config.utils.load_forge_config")
    async def test_get_global_config_memory_hit(self, mock_load, cache):
        fake = MagicMock()
        cache._global_config_cache = fake
        cache._global_config_time = time.time()
        result = await cache.get_global_config()
        assert result is fake
        mock_load.assert_not_called()

    @pytest.mark.asyncio
    @patch("backend.core.config.utils.load_forge_config")
    async def test_get_global_config_memory_expired(self, mock_load, cache):
        new_config = MagicMock()
        mock_load.return_value = new_config
        cache._global_config_cache = MagicMock()
        cache._global_config_time = time.time() - 600
        result = await cache.get_global_config()
        assert result is new_config

    @pytest.mark.asyncio
    async def test_get_user_settings_memory_hit(self, cache):
        fake_settings = MagicMock()
        cache._user_settings_cache["u1"] = (fake_settings, time.time())
        store = AsyncMock()
        result = await cache.get_user_settings("u1", store)
        assert result is fake_settings
        store.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_settings_memory_miss(self, cache):
        loaded = MagicMock()
        loaded.merge_with_config_settings.return_value = loaded
        store = AsyncMock()
        store.load.return_value = loaded
        with patch(
            "backend.core.config.utils.load_forge_config", return_value=MagicMock()
        ):
            with patch(
                "backend.core.cache.async_smart_cache.merge_settings_with_cache",
                return_value=loaded,
            ):
                result = await cache.get_user_settings("u1", store)
        assert result is loaded

    @pytest.mark.asyncio
    async def test_get_user_settings_returns_none(self, cache):
        store = AsyncMock()
        store.load.return_value = None
        result = await cache.get_user_settings("u1", store)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_user_cache(self, cache):
        cache._user_settings_cache["u1"] = (MagicMock(), time.time())
        await cache.invalidate_user_cache("u1")
        assert "u1" not in cache._user_settings_cache

    @pytest.mark.asyncio
    async def test_invalidate_global_cache(self, cache):
        cache._global_config_cache = MagicMock()
        cache._global_config_time = time.time()
        await cache.invalidate_global_cache()
        assert cache._global_config_cache is None
        assert cache._global_config_time == 0

    @pytest.mark.asyncio
    async def test_get_cache_stats_memory(self, cache):
        stats = await cache.get_cache_stats()
        assert stats["cache_type"] == "memory"
        assert stats["global_config_cached"] is False
        assert stats["cached_users"] == 0

    @pytest.mark.asyncio
    async def test_close_without_client(self, cache):
        await cache.close()  # Should not raise


class TestAsyncSmartCacheSingleton:
    @pytest.mark.asyncio
    async def test_get_async_smart_cache(self):
        import backend.core.cache.async_smart_cache as mod

        mod._async_smart_cache = None
        instance = await mod.get_async_smart_cache()
        assert isinstance(instance, mod.AsyncSmartCache)
        assert await mod.get_async_smart_cache() is instance
        mod._async_smart_cache = None


class TestAsyncSmartCacheRedis:
    @pytest.mark.asyncio
    async def test_ensure_connection_uses_existing_client(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.ping.return_value = True

        assert await cache._ensure_connection() is True
        cache.redis_client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_connection_reconnects(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True

        failed_client = AsyncMock()
        failed_client.ping.side_effect = Exception("down")
        cache.redis_client = failed_client

        new_client = AsyncMock()
        new_client.ping.return_value = True

        with patch.object(mod, "aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=new_client)
            with patch(
                "backend.core.cache.async_smart_cache.get_redis_connection_params",
                return_value={},
            ):
                assert await cache._ensure_connection() is True
        assert cache.redis_client is new_client

    @pytest.mark.asyncio
    async def test_get_global_config_redis_hit(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.return_value = b"payload"

        with patch(
            "backend.core.cache.async_smart_cache.deserialize_model",
            return_value=MagicMock(),
        ) as mock_deserialize:
            result = await cache._get_global_config_redis()
        assert result is mock_deserialize.return_value

    @pytest.mark.asyncio
    async def test_get_global_config_redis_miss(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.return_value = None

        fake_config = MagicMock()
        with patch(
            "backend.core.config.utils.load_forge_config", return_value=fake_config
        ):
            with patch(
                "backend.core.cache.async_smart_cache.serialize_model",
                return_value=b"blob",
            ):
                result = await cache._get_global_config_redis()

        assert result is fake_config
        cache.redis_client.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_global_config_redis_error_falls_back(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.side_effect = Exception("boom")

        with patch.object(cache, "_get_global_config_memory", return_value=MagicMock()):
            result = await cache._get_global_config_redis()
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_hit(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.return_value = b"payload"

        with patch(
            "backend.core.cache.async_smart_cache.deserialize_model",
            return_value=MagicMock(),
        ) as mock_deserialize:
            result = await cache._get_user_settings_redis("u1", AsyncMock())
        assert result is mock_deserialize.return_value

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_miss_no_global_config(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.return_value = None

        loaded_settings = MagicMock()
        store = AsyncMock()
        store.load.return_value = loaded_settings

        with patch.object(cache, "get_global_config", AsyncMock(return_value=None)):
            with patch(
                "backend.core.cache.async_smart_cache.serialize_model",
                return_value=b"blob",
            ):
                result = await cache._get_user_settings_redis("u1", store)

        assert result is loaded_settings
        cache.redis_client.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_error_falls_back(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.side_effect = Exception("down")

        with patch.object(
            cache, "_get_user_settings_memory", AsyncMock(return_value=MagicMock())
        ) as mock_fallback:
            result = await cache._get_user_settings_redis("u1", AsyncMock())
        assert result is mock_fallback.return_value

    @pytest.mark.asyncio
    async def test_invalidate_user_cache_handles_redis_error(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.delete.side_effect = Exception("fail")

        cache._user_settings_cache["u1"] = (MagicMock(), time.time())
        await cache.invalidate_user_cache("u1")
        assert "u1" not in cache._user_settings_cache

    @pytest.mark.asyncio
    async def test_get_cache_stats_redis(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.info.return_value = {"used_memory": 0}
        cache.redis_client.keys.side_effect = [["global"], ["user1"]]

        with patch(
            "backend.core.cache.async_smart_cache.extract_redis_stats",
            return_value={"key_count": 2},
        ):
            stats = await cache.get_cache_stats()

        assert stats["cache_type"] == "redis"
        assert stats["key_count"] == 2

    @pytest.mark.asyncio
    async def test_close_handles_client_error(self):
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_client = AsyncMock()
        cache.redis_client.close.side_effect = Exception("close")

        await cache.close()

    @pytest.mark.asyncio
    async def test_ensure_connection_fails_to_connect(self):
        """Test connection failure exception path (lines 121-124)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = None

        with patch.object(mod, "aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(
                side_effect=Exception("connection failed")
            )
            with patch(
                "backend.core.cache.async_smart_cache.get_redis_connection_params",
                return_value={},
            ):
                assert await cache._ensure_connection() is False
        # Should have set client to None after failure
        assert cache.redis_client is None

    @pytest.mark.asyncio
    async def test_get_global_config_redis_with_none_client(self):
        """Test _get_global_config_redis fallback when client is None (line 134)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = None  # Explicitly None

        fake_config = MagicMock()
        with patch.object(cache, "_get_global_config_memory", return_value=fake_config):
            result = await cache._get_global_config_redis()

        assert result is fake_config

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_with_none_client(self):
        """Test _get_user_settings_redis fallback when client is None (line 211)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = None

        fake_settings = MagicMock()
        with patch.object(
            cache, "_get_user_settings_memory", return_value=fake_settings
        ):
            result = await cache._get_user_settings_redis("u1", AsyncMock())

        assert result is fake_settings

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_loaded_settings_none(self):
        """Test when loaded_settings is None (line 240)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.return_value = None  # Cache miss

        store = AsyncMock()
        store.load.return_value = None  # No settings in DB

        result = await cache._get_user_settings_redis("u1", store)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_no_global_config(self):
        """Test when global_config is None (line 245)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.get.return_value = None  # Cache miss

        fake_settings = MagicMock()
        fake_settings.merge_with_config_settings.return_value = fake_settings
        store = AsyncMock()
        store.load.return_value = fake_settings

        # Mock get_global_config to return None
        with patch.object(cache, "get_global_config", return_value=None):
            with patch(
                "backend.core.cache.async_smart_cache.serialize_model",
                return_value=b"blob",
            ):
                result = await cache._get_user_settings_redis("u1", store)

        # Should use loaded_settings directly without merging
        assert result is fake_settings

    @pytest.mark.asyncio
    async def test_invalidate_global_cache_redis_error(self):
        """Test invalidate_global_cache exception handler (lines 321-327)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.delete.side_effect = Exception("delete failed")

        # Should not raise, should fall back to memory invalidation
        await cache.invalidate_global_cache()

        # Memory cache should be invalidated
        assert cache._global_config_cache is None
        assert cache._global_config_time == 0

    @pytest.mark.asyncio
    async def test_get_cache_stats_redis_error(self):
        """Test get_cache_stats exception handler (lines 358-359)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()
        cache.redis_client.info.side_effect = Exception("info failed")

        stats = await cache.get_cache_stats()

        # Should have redis_error in stats
        assert "redis_error" in stats
        assert stats["cache_type"] == "redis"

    @pytest.mark.asyncio
    async def test_invalidate_user_cache_redis_with_connection(self):
        """Test invalidate_user_cache with successful redis delete (line 306 exception path)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = AsyncMock()

        # Simulate successful connection
        with patch.object(cache, "_ensure_connection", return_value=True):
            cache._user_settings_cache["u1"] = (MagicMock(), time.time())

            # Make delete fail to hit exception handler (line 306)
            cache.redis_client.delete.side_effect = Exception("delete failed")

            await cache.invalidate_user_cache("u1")

        # Memory cache should still be invalidated
        assert "u1" not in cache._user_settings_cache

    @pytest.mark.asyncio
    async def test_ensure_connection_ping_fails_then_reconnects(self):
        """Test ping() exception and reconnect path (lines 104-108)."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True

        # Setup failing client
        failed_client = AsyncMock()
        failed_client.ping = AsyncMock(side_effect=Exception("ping down"))
        cache.redis_client = failed_client

        # Setup new successful client
        new_client = AsyncMock()
        new_client.ping = AsyncMock(return_value=True)

        with patch.object(mod, "aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=new_client)
            with patch(
                "backend.core.cache.async_smart_cache.get_redis_connection_params",
                return_value={},
            ):
                result = await cache._ensure_connection()

        # Should reconnect successfully
        assert result is True
        assert cache.redis_client is new_client

    @pytest.mark.asyncio
    async def test_get_global_config_redis_path_without_connection(self):
        """Test calling _get_global_config_redis when _ensure_connection returns False."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = None  # No client

        # Call get_global_config which should try to ensure connection, fail, then use memory
        fake_config = MagicMock()
        with patch.object(cache, "_ensure_connection", return_value=False):
            with patch.object(
                cache, "_get_global_config_memory", return_value=fake_config
            ):
                result = await cache.get_global_config()

        assert result is fake_config

    @pytest.mark.asyncio
    async def test_get_user_settings_redis_path_without_connection(self):
        """Test calling _get_user_settings_redis when ensure_connection returns False."""
        import backend.core.cache.async_smart_cache as mod

        cache = mod.AsyncSmartCache()
        cache.redis_available = True
        cache.redis_client = None

        fake_settings = MagicMock()
        store = AsyncMock()

        with patch.object(cache, "_ensure_connection", return_value=False):
            with patch.object(
                cache, "_get_user_settings_memory", return_value=fake_settings
            ):
                result = await cache.get_user_settings("u1", store)

        assert result is fake_settings
