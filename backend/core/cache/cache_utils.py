"""Shared utilities for in-memory settings caching."""

from typing import Any, TypeVar

T = TypeVar('T')


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

    # Bounded cache (evict oldest if > 256 users)
    if len(cache) >= 256 and user_id not in cache:
        oldest_key = next(iter(cache))
        del cache[oldest_key]
    cache[user_id] = (merged_settings, current_time)
    return merged_settings
