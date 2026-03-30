"""Factory for creating distributed cache instances with standard error handling."""

from __future__ import annotations

from backend.core.logger import app_logger as logger

# Optional distributed cache availability check
try:
    from backend.core.cache import DistributedCache

    DISTRIBUTED_CACHE_AVAILABLE = True
except ImportError:
    DISTRIBUTED_CACHE_AVAILABLE = False


def create_distributed_cache(
    prefix: str,
    ttl_seconds: int,
    max_connections: int = 50,
) -> DistributedCache | None:
    """Create and initialize a DistributedCache instance if available.

    Args:
        prefix: Key prefix for the cache
        ttl_seconds: Default TTL for cache entries
        max_connections: Maximum Redis connections

    Returns:
        Initialized DistributedCache or None if unavailable or failed.
    """
    if not DISTRIBUTED_CACHE_AVAILABLE:
        logger.debug("Distributed cache not available, using local-only mode")
        return None

    try:
        cache = DistributedCache(
            prefix=prefix,
            ttl_seconds=ttl_seconds,
            max_connections=max_connections,
        )
        if cache.enabled:
            return cache
        return None
    except Exception as e:
        logger.warning("Failed to init distributed cache for %s: %s", prefix, e)
        return None
