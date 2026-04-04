"""Async in-memory cache for the Settings API."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from backend.core.cache.cache_utils import merge_settings_with_cache
from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig
    from backend.persistence.data_models.settings import Settings
    from backend.persistence.settings.settings_store import SettingsStore


class AsyncSmartCache:
    """Async in-memory cache for Settings API performance."""

    def __init__(
        self,
        redis_host: str = 'redis',
        redis_port: int = 6379,
        redis_password: str = '',
    ):
        """Initialize async smart cache.

        The Redis-related arguments are kept for backward compatibility with
        existing call sites and environment-driven factories.
        """
        _ = (redis_host, redis_port, redis_password)
        self.redis_available = False
        self.redis_client: Any | None = None
        self._connection_lock = asyncio.Lock()
        self._global_config_cache: AppConfig | None = None
        self._global_config_time: float = 0
        self._user_settings_cache: dict[str, tuple[Settings, float]] = {}
        logger.info('AsyncSmartCache: using in-memory cache')

    async def _ensure_connection(self) -> bool:
        """Retained for compatibility; Redis is no longer used."""
        return False

    async def get_global_config(self) -> AppConfig | None:
        """Get global app config with intelligent caching.

        Returns:
            Global AppConfig or None if not available

        """
        return self._get_global_config_memory()

    def _get_global_config_memory(self) -> AppConfig | None:
        """Get global config from memory cache."""
        current_time = time.time()

        # Check cache (5min TTL)
        if (
            self._global_config_cache is not None
            and current_time - self._global_config_time < 300
        ):
            logger.debug('Global config cache hit (memory)')
            return self._global_config_cache

        # Cache miss - load from file
        from backend.core.config.config_loader import load_app_config

        config = load_app_config()

        # Cache in memory
        self._global_config_cache = config
        self._global_config_time = current_time
        logger.debug('Global config cache miss - loaded and cached (memory)')
        return config

    async def get_user_settings(
        self, user_id: str, settings_store: SettingsStore
    ) -> Settings | None:
        """Get user settings with in-memory caching."""
        return await self._get_user_settings_memory(user_id, settings_store)

    async def _get_user_settings_memory(
        self, user_id: str, settings_store: SettingsStore
    ) -> Settings | None:
        """Get user settings from memory cache."""
        current_time = time.time()

        # Check cache (1min TTL)
        if user_id in self._user_settings_cache:
            cached_settings, cached_time = self._user_settings_cache[user_id]
            if current_time - cached_time < 60:
                logger.debug("User settings cache hit for '%s' (memory)", user_id)
                return cached_settings

        # Cache miss - load from database and merge
        logger.debug("User settings cache miss for '%s' - loading from DB", user_id)
        settings = await settings_store.load()
        if not settings:
            return None

        # Merge with global config and cache
        global_config = await self.get_global_config()
        merged_settings = merge_settings_with_cache(
            user_id, settings, global_config, self._user_settings_cache, current_time
        )
        logger.debug("Cached merged settings for '%s' (memory, TTL: 60s)", user_id)
        return merged_settings

    async def invalidate_user_cache(self, user_id: str) -> None:
        """Invalidate cache for a specific user (when settings change).

        Args:
            user_id: User identifier to invalidate

        """
        if user_id in self._user_settings_cache:
            del self._user_settings_cache[user_id]
            logger.debug("Invalidated memory cache for user '%s'", user_id)

    async def invalidate_global_cache(self) -> None:
        """Invalidate global config cache (when settings.json changes)."""
        self._global_config_cache = None
        self._global_config_time = 0
        logger.info('Invalidated global config cache (memory)')

    async def get_cache_stats(self) -> dict:
        """Get cache statistics for monitoring.

        Returns:
            Dictionary with cache statistics

        """
        stats: dict[str, Any] = {
            'redis_available': False,
            'cache_type': 'memory',
            'global_config_cached': self._global_config_cache is not None,
            'cached_users': len(self._user_settings_cache),
        }
        return stats

    async def close(self) -> None:
        """Retained for API compatibility."""
        self.redis_client = None


# Global instance for easy access
_async_smart_cache: AsyncSmartCache | None = None


async def get_async_smart_cache() -> AsyncSmartCache:
    """Get global AsyncSmartCache instance."""
    global _async_smart_cache
    if _async_smart_cache is None:
        _async_smart_cache = AsyncSmartCache()
    return _async_smart_cache
