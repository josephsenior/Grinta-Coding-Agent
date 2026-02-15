"""Shared utilities for Redis caching."""

from typing import Any, TypeVar

T = TypeVar("T")


def extract_redis_stats(
    info: dict[str, Any], global_keys: list, user_keys: list
) -> dict[str, Any]:
    """Extract standard statistics from Redis info and keys."""
    return {
        "redis_used_memory_mb": info.get("used_memory", 0) / 1024 / 1024,
        "redis_total_commands": info.get("total_commands_processed", 0),
        "redis_keyspace_hits": info.get("keyspace_hits", 0),
        "redis_keyspace_misses": info.get("keyspace_misses", 0),
        "global_config_cached": len(global_keys) > 0,
        "cached_users": len(user_keys),
    }


def merge_settings_with_cache(
    user_id: str,
    settings: T,
    global_config: Any,
    cache: dict[str, tuple[T, float]],
    current_time: float,
) -> T:
    """Shared logic for merging settings and updating memory cache."""
    if global_config:
        merged_settings = settings.merge_with_config_settings()  # type: ignore
    else:
        merged_settings = settings

    # Bounded LRU cache (evict oldest if > 256 users)
    if len(cache) >= 256 and user_id not in cache:
        oldest_key = next(iter(cache))
        del cache[oldest_key]
    cache[user_id] = (merged_settings, current_time)
    return merged_settings


def get_redis_connection_params(
    host: str, port: int, password: str | None = None
) -> dict[str, Any]:
    """Get standard Redis connection parameters.

    Returns:
        Dictionary of connection parameters.
    """
    return {
        "decode_responses": False,
        "socket_connect_timeout": 5,
        "socket_timeout": 10,
        "retry_on_timeout": True,
        "health_check_interval": 30,
    }
