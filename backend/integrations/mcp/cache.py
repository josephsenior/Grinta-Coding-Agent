"""Simple in-process cache for MCP tool results.

This cache is intentionally minimal:
 - Per-process (not shared across workers)
 - Time-based invalidation (TTL)
 - Optional size guard to avoid storing very large payloads
 - Skips caching error responses (heuristic: presence of 'isError' True)

Key format: f"{tool_name}::${stable_args_json}" where args JSON is sorted keys
Refresh/skip: if arguments contain any of {"refresh": true, "no_cache": true} we bypass cache
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from backend.core.constants import (
    DEFAULT_MCP_CACHE_TTL_SECONDS,
    MAX_MCP_CACHE_ENTRY_BYTES,
    MCP_CACHEABLE_TOOLS,
)
from backend.core.logger import app_logger as logger

DEFAULT_TTL_SECONDS = DEFAULT_MCP_CACHE_TTL_SECONDS
try:
    MAX_CACHE_ENTRY_BYTES = int(
        os.getenv('APP_MCP_CACHE_MAX_ENTRY_BYTES', str(MAX_MCP_CACHE_ENTRY_BYTES))
    )
except ValueError:
    MAX_CACHE_ENTRY_BYTES = MAX_MCP_CACHE_ENTRY_BYTES
_CACHEABLE_TOOLS = MCP_CACHEABLE_TOOLS


@dataclass
class CacheEntry:
    """Internal cache entry containing value, expiry timestamp, and serialized size."""

    value: dict
    expires_at: float
    size: int


_tool_cache: dict[str, CacheEntry] = {}


def is_cacheable(tool_name: str) -> bool:
    """Return True if the tool name participates in caching."""
    return tool_name in _CACHEABLE_TOOLS


def _stable_args_json(args: dict) -> str:
    """Serialize arguments deterministically, dropping refresh/no_cache flags."""
    filtered = {
        k: v
        for k, v in sorted(args.items(), key=lambda kv: kv[0])
        if k not in {'refresh', 'no_cache'}
    }
    return json.dumps(filtered, separators=(',', ':'), ensure_ascii=False)


def build_cache_key(tool_name: str, args: dict) -> str:
    """Construct normalized cache key for tool invocation."""
    return f'{tool_name}::{_stable_args_json(args)}'


def get_cached(tool_name: str, args: dict) -> dict | None:
    """Return cached result if present and still valid, otherwise None."""
    if not is_cacheable(tool_name):
        return None
    if args.get('refresh') or args.get('no_cache'):
        return None
    key = build_cache_key(tool_name, args)
    entry = _tool_cache.get(key)
    if not entry:
        return None
    if entry.expires_at < time.time():
        _tool_cache.pop(key, None)
        return None
    return entry.value


def set_cache(
    tool_name: str, args: dict, result_dict: dict, ttl: int = DEFAULT_TTL_SECONDS
) -> None:
    """Store result_dict in cache when tool is cacheable and payload acceptable."""
    if not is_cacheable(tool_name):
        return
    if args.get('refresh') or args.get('no_cache'):
        return
    if result_dict.get('isError') or (
        isinstance(result_dict.get('content'), dict)
        and result_dict['content'].get('isError')
    ):
        return
    raw = json.dumps(result_dict, ensure_ascii=False).encode('utf-8')
    if len(raw) > MAX_CACHE_ENTRY_BYTES:
        logger.debug(
            'Skipping cache set for %s (size %d > limit %d)',
            tool_name,
            len(raw),
            MAX_CACHE_ENTRY_BYTES,
        )
        return
    key = build_cache_key(tool_name, args)
    _tool_cache[key] = CacheEntry(
        value=result_dict, expires_at=time.time() + ttl, size=len(raw)
    )


def clear_cache(prefix: str | None = None) -> int:
    """Clear all cache entries or those matching a tool prefix.

    Returns number of entries removed.
    """
    to_delete: list[str] = []
    if prefix:
        to_delete.extend(k for k in _tool_cache if k.startswith(f'{prefix}::'))
    else:
        to_delete = list(_tool_cache.keys())
    for k in to_delete:
        _tool_cache.pop(k, None)
    return len(to_delete)
