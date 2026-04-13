"""Tests for backend.core.cache.smart_config_cache."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import backend.core.cache.smart_config_cache as mod


class TestSmartConfigCache:
    def test_initializes_memory_cache(self):
        cache = mod.SmartConfigCache()

        assert cache.redis_available is False
        assert cache._global_config_cache is None
        assert cache._global_config_time == 0
        assert cache._user_settings_cache == {}

    @patch('backend.core.config.config_loader.load_app_config')
    def test_get_global_config_memory_miss(self, mock_load):
        fake_config = MagicMock()
        mock_load.return_value = fake_config
        cache = mod.SmartConfigCache()

        result = cache.get_global_config()

        assert result is fake_config
        assert cache._global_config_cache is fake_config

    @patch('backend.core.config.config_loader.load_app_config')
    def test_get_global_config_memory_hit(self, mock_load):
        cache = mod.SmartConfigCache()
        fake_config = MagicMock()
        cache._global_config_cache = fake_config
        cache._global_config_time = time.time()

        result = cache.get_global_config()

        assert result is fake_config
        mock_load.assert_not_called()

    @patch('backend.core.cache.smart_config_cache.merge_settings_with_cache')
    @patch('backend.core.config.config_loader.load_app_config')
    def test_get_user_settings_memory_miss(self, mock_load_cfg, mock_merge):
        cache = mod.SmartConfigCache()
        settings_store = MagicMock()
        settings = MagicMock()
        settings_store.load.return_value = settings
        mock_load_cfg.return_value = MagicMock()
        mock_merge.return_value = settings

        result = cache.get_user_settings('user-1', settings_store, MagicMock())

        assert result is settings
        settings_store.load.assert_called_once()

    def test_get_user_settings_memory_hit(self):
        cache = mod.SmartConfigCache()
        settings = MagicMock()
        cache._user_settings_cache['user-1'] = (settings, time.time())

        result = cache.get_user_settings('user-1', MagicMock(), MagicMock())

        assert result is settings

    def test_invalidate_caches(self):
        cache = mod.SmartConfigCache()
        cache._global_config_cache = MagicMock()
        cache._global_config_time = time.time()
        cache._user_settings_cache['user-1'] = (MagicMock(), time.time())

        cache.invalidate_user_cache('user-1')
        cache.invalidate_global_cache()

        assert 'user-1' not in cache._user_settings_cache
        assert cache._global_config_cache is None
        assert cache._global_config_time == 0  # type: ignore

    def test_get_cache_stats(self):
        cache = mod.SmartConfigCache()
        stats = cache.get_cache_stats()

        assert stats['redis_available'] is False
        assert stats['cache_type'] == 'memory'
        assert stats['global_config_cached'] is False
        assert stats['cached_users'] == 0


class TestGetSmartCacheSingleton:
    def test_returns_singleton(self):
        mod._smart_cache = None

        instance = mod.get_smart_cache()

        assert isinstance(instance, mod.SmartConfigCache)
        assert mod.get_smart_cache() is instance
        mod._smart_cache = None
