"""Multi-layer caching strategy for Forge.

Provides L1 (in-memory), L2 (Redis), and L3 (database) caching layers.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    pass

T = TypeVar("T")

# L1 Cache: In-memory (per-worker)
_l1_cache: dict[str, tuple[Any, float]] = {}
_l1_cache_size_limit = 1000

# Redis client (L2 Cache) - lazy initialization
_redis_client: Any | None = None


def get_redis_client():
    """Get or create Redis client for L2 cache."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    redis_url = os.getenv("REDIS_URL") or os.getenv("REDIS_CONNECTION_URL")
    if not redis_url:
        return None

    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        _redis_client.ping()  # Test connection
        logger.info("Redis cache (L2) initialized")
        return _redis_client
    except Exception as e:
        logger.warning("Redis cache unavailable: %s", e)
        return None


class CacheKey:
    """Helper for building cache keys."""

    @staticmethod
    def build(*parts: str, prefix: str = "forge") -> str:
        """Build a cache key from parts.

        Args:
            *parts: Key parts to join
            prefix: Key prefix (default: "forge")

        Returns:
            Cache key string
        """
        return ":".join([prefix] + [str(p) for p in parts])


def get(key: str, default: Any = None, ttl: int | None = None) -> Any:
    """Get value from cache (checks L1, then L2).

    Args:
        key: Cache key
        default: Default value if not found
        ttl: Optional TTL override (for L2 cache)

    Returns:
        Cached value or default
    """
    # Try L1 cache first
    if key in _l1_cache:
        value, expiry = _l1_cache[key]
        if expiry == 0 or time.time() < expiry:
            return value
        # Expired, remove from L1
        del _l1_cache[key]

    # Try L2 cache (Redis)
    redis_client = get_redis_client()
    if redis_client:
        try:
            cached = redis_client.get(key)
            if cached:
                value = json.loads(cached)
                # Also store in L1 for faster access
                set_value(key, value, ttl=ttl, layer="l1")
                return value
        except Exception as e:
            logger.debug("Redis cache get error: %s", e)

    return default


def set_value(
    key: str,
    value: Any,
    ttl: int | None = None,
    layer: str = "all",
) -> None:
    """Set value in cache.

    Args:
        key: Cache key
        value: Value to cache
        ttl: Time to live in seconds (None = no expiration)
        layer: Which layer to use ("l1", "l2", "all")
    """
    expiry = time.time() + ttl if ttl else 0

    # L1 cache
    if layer in ("l1", "all"):
        # Enforce size limit
        if len(_l1_cache) >= _l1_cache_size_limit:
            # Remove oldest entry (simple FIFO)
            oldest_key = next(iter(_l1_cache))
            del _l1_cache[oldest_key]

        _l1_cache[key] = (value, expiry)

    # L2 cache (Redis)
    if layer in ("l2", "all"):
        redis_client = get_redis_client()
        if redis_client:
            try:
                serialized = json.dumps(value)
                if ttl:
                    redis_client.setex(key, ttl, serialized)
                else:
                    redis_client.set(key, serialized)
            except Exception as e:
                logger.debug("Redis cache set error: %s", e)


def delete(key: str, layer: str = "all") -> None:
    """Delete value from cache.

    Args:
        key: Cache key
        layer: Which layer to clear ("l1", "l2", "all")
    """
    if layer in ("l1", "all"):
        _l1_cache.pop(key, None)

    if layer in ("l2", "all"):
        redis_client = get_redis_client()
        if redis_client:
            try:
                redis_client.delete(key)
            except Exception as e:
                logger.debug("Redis cache delete error: %s", e)


def clear(layer: str = "all") -> None:
    """Clear all cache.

    Args:
        layer: Which layer to clear ("l1", "l2", "all")
    """
    if layer in ("l1", "all"):
        _l1_cache.clear()

    if layer in ("l2", "all"):
        redis_client = get_redis_client()
        if redis_client:
            try:
                redis_client.flushdb()
            except Exception as e:
                logger.debug("Redis cache clear error: %s", e)


def cached(
    key_prefix: str,
    ttl: int = 300,
    key_builder: Callable[..., str] | None = None,
):
    """Decorator to cache function results.

    Args:
        key_prefix: Prefix for cache keys
        ttl: Time to live in seconds
        key_builder: Optional function to build cache key from args/kwargs

    Example:
        @cached("user_profile", ttl=600)
        async def get_user_profile(user_id: str):
            ...
    """

    def decorator(
        func: Callable[..., T] | Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., T] | Callable[..., Coroutine[Any, Any, T]]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                # Default: use function name + args hash
                key_parts = [key_prefix, func.__name__]
                if args:
                    key_parts.append(str(hash(args)))
                if kwargs:
                    key_parts.append(str(hash(tuple(sorted(kwargs.items())))))
                cache_key = CacheKey.build(*key_parts)

            # Try cache
            cached_value = get(cache_key)
            if cached_value is not None:
                return cached_value  # type: ignore[return-value]

            # Call function - func is async here, so it returns a coroutine
            async_func = func  # type: ignore[assignment]
            result = await async_func(*args, **kwargs)  # type: ignore[misc]

            # Store in cache
            set(cache_key, result, ttl=ttl)

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                key_parts = [key_prefix, func.__name__]
                if args:
                    key_parts.append(str(hash(args)))
                if kwargs:
                    key_parts.append(str(hash(tuple(sorted(kwargs.items())))))
                cache_key = CacheKey.build(*key_parts)

            # Try cache
            cached_value = get(cache_key)
            if cached_value is not None:
                return cached_value  # type: ignore[return-value]

            # Call function
            result = func(*args, **kwargs)  # type: ignore[misc]

            # Store in cache
            set(cache_key, result, ttl=ttl)

            return result  # type: ignore[return-value]

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
