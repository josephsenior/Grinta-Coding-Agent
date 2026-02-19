"""File Caching System - Fast Repeated Access.

Caches parsed files and symbol locations for instant lookup.
Dramatically improves performance for repeated file access.

Supports both local (single-instance) and distributed (Redis, multi-instance) modes.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from backend.core.logger import forge_logger as logger

from backend.core.cache.factory import create_distributed_cache


class FileCache:
    """Fast file caching system for Auditor.

    Features:
    - Caches file content and parsed data
    - Symbol location caching
    - TTL-based expiration
    - Memory-efficient (LRU eviction)
    - File modification tracking
    """

    def __init__(
        self,
        max_cache_size: int = 100,  # Max files to cache
        ttl_seconds: int = 300,  # 5 minutes
        enable_mtime_check: bool = True,  # Invalidate on file modification
        use_distributed: bool = True,  # Use Redis if available
    ):
        """Initialize file cache with optional distributed (Redis) backend.

        Args:
            max_cache_size: Maximum number of files to cache
            ttl_seconds: Time-to-live for cache entries
            enable_mtime_check: Check file modification time
            use_distributed: Use Redis distributed cache if available (recommended for 1000+ users)

        """
        self.max_cache_size = max_cache_size
        self.ttl = timedelta(seconds=ttl_seconds)
        self.enable_mtime_check = enable_mtime_check

        # Try to use distributed cache if requested and available
        self.distributed_cache = None
        if use_distributed:
            self.distributed_cache = create_distributed_cache(
                prefix="forge:file_cache",
                ttl_seconds=ttl_seconds,
            )
            if self.distributed_cache:
                logger.info(
                    "📦 File cache using REDIS distributed backend (perfect for 1000+ users!)"
                )

        # Local cache (used when distributed unavailable OR as L1 cache)
        self.content_cache: dict[
            str, tuple[str, datetime, float]
        ] = {}  # path → (content, cached_at, mtime)
        self.symbol_cache: dict[
            str, dict[str, Any]
        ] = {}  # path → {symbol_name → location}
        self.structure_cache: dict[str, dict[str, Any]] = {}  # path → file structure

        # Access tracking for LRU
        self.access_times: dict[str, datetime] = {}

        # Stats
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "invalidations": 0,
            "distributed_hits": 0,
            "distributed_misses": 0,
        }

        cache_mode = "distributed (Redis)" if self.distributed_cache else "local"
        logger.info(
            "📦 File cache initialized (mode=%s, max_size=%s, ttl=%ss)",
            cache_mode,
            max_cache_size,
            ttl_seconds,
        )

    def _check_distributed_cache(self, file_path: str) -> str | None:
        """Check distributed cache (L2) for file content.

        Args:
            file_path: Path to file

        Returns:
            File content if found and valid, None otherwise

        """
        if not self.distributed_cache:
            return None

        try:
            cached_data = self.distributed_cache.get(file_path)
            if not cached_data:
                self.stats["distributed_misses"] += 1
                return None

            content, cached_at_iso, mtime = cached_data
            cached_at = datetime.fromisoformat(cached_at_iso)

            if self.enable_mtime_check:
                if not self._validate_mtime(file_path, mtime):
                    return None

            self.content_cache[file_path] = (content, cached_at, mtime)
            self.access_times[file_path] = datetime.now()
            self.stats["distributed_hits"] += 1
            self.stats["hits"] += 1
            return content
        except Exception as e:
            logger.debug("Distributed cache error: %s", e)
            return None

    def _validate_mtime(self, file_path: str, cached_mtime: float) -> bool:
        """Validate file modification time matches cached value.

        Args:
            file_path: Path to file
            cached_mtime: Cached modification time

        Returns:
            True if mtime matches, False otherwise

        """
        try:
            current_mtime = os.path.getmtime(file_path)
            if current_mtime != cached_mtime:
                cache = self.distributed_cache
                if cache:
                    cache.delete(file_path)
                self.stats["distributed_misses"] += 1
                self.stats["misses"] += 1
                return False
            return True
        except (OSError, FileNotFoundError):
            cache = self.distributed_cache
            if cache:
                cache.delete(file_path)
            self.stats["distributed_misses"] += 1
            self.stats["misses"] += 1
            return False

    def _check_local_cache(self, file_path: str) -> str | None:
        """Check local cache (L1) for file content.

        Args:
            file_path: Path to file

        Returns:
            File content if found and valid, None otherwise

        """
        if file_path not in self.content_cache:
            return None

        content, cached_at, cached_mtime = self.content_cache[file_path]

        if datetime.now() - cached_at > self.ttl:
            self._invalidate_file(file_path)
            self.stats["misses"] += 1
            return None

        # Check file modification time
        if self.enable_mtime_check:
            try:
                current_mtime = os.path.getmtime(file_path)
                if current_mtime != cached_mtime:
                    self._invalidate_file(file_path)
                    self.stats["misses"] += 1
                    return None
            except (OSError, FileNotFoundError):
                self._invalidate_file(file_path)
                self.stats["misses"] += 1
                return None

        # Cache hit!
        self.stats["hits"] += 1
        self.access_times[file_path] = datetime.now()
        return content

    def get_content(self, file_path: str) -> str | None:
        """Get cached file content with 2-tier caching (L1 local, L2 Redis).

        Args:
            file_path: Path to file

        Returns:
            File content if cached and valid, None otherwise

        """
        # L1: Check local cache first (fastest)
        content = self._check_local_cache(file_path)
        if content is not None:
            return content

        # L2: Check distributed cache (if available)
        content = self._check_distributed_cache(file_path)
        if content is not None:
            return content

        self.stats["misses"] += 1
        return None

    def cache_content(self, file_path: str, content: str) -> None:
        """Cache file content in both L1 (local) and L2 (Redis) if available.

        Args:
            file_path: Path to file
            content: File content

        """
        # Get file modification time
        try:
            mtime = os.path.getmtime(file_path) if self.enable_mtime_check else 0.0
        except (OSError, FileNotFoundError):
            mtime = 0.0

        # Store in distributed cache (L2) for sharing across instances
        if self.distributed_cache:
            try:
                cached_data = (content, datetime.now().isoformat(), mtime)
                self.distributed_cache.set(file_path, cached_data)
            except Exception as e:
                logger.debug("Failed to cache in Redis: %s", e)

        # Check cache size and evict if needed
        if len(self.content_cache) >= self.max_cache_size:
            self._evict_lru()

        # Cache the content
        self.content_cache[file_path] = (content, datetime.now(), mtime)
        self.access_times[file_path] = datetime.now()

        logger.debug("💾 Cached: %s", file_path)

    def cache_symbols(self, file_path: str, symbols: dict[str, Any]) -> None:
        """Cache symbol locations for a file.

        Args:
            file_path: Path to file
            symbols: Dictionary of {symbol_name: location_info}

        """
        self.symbol_cache[file_path] = symbols
        self.access_times[file_path] = datetime.now()

    def get_symbols(self, file_path: str) -> dict[str, Any] | None:
        """Get cached symbols for a file."""
        if file_path in self.symbol_cache:
            self.stats["hits"] += 1
            self.access_times[file_path] = datetime.now()
            return self.symbol_cache[file_path]

        self.stats["misses"] += 1
        return None

    def cache_structure(self, file_path: str, structure: dict[str, Any]) -> None:
        """Cache file structure (classes, functions, etc.).

        Args:
            file_path: Path to file
            structure: File structure information

        """
        self.structure_cache[file_path] = structure
        self.access_times[file_path] = datetime.now()

    def get_structure(self, file_path: str) -> dict[str, Any] | None:
        """Get cached file structure."""
        if file_path in self.structure_cache:
            self.stats["hits"] += 1
            self.access_times[file_path] = datetime.now()
            return self.structure_cache[file_path]

        self.stats["misses"] += 1
        return None

    def _invalidate_file(self, file_path: str) -> None:
        """Invalidate all cached data for a file."""
        self.content_cache.pop(file_path, None)
        self.symbol_cache.pop(file_path, None)
        self.structure_cache.pop(file_path, None)
        self.access_times.pop(file_path, None)
        self.stats["invalidations"] += 1
        logger.debug("🗑️  Invalidated cache: %s", file_path)

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self.access_times:
            return

        # Find least recently accessed
        lru_path = min(self.access_times.items(), key=lambda x: x[1])[0]

        # Evict it
        self._invalidate_file(lru_path)
        self.stats["evictions"] += 1
        logger.debug("📤 Evicted LRU: %s", lru_path)

    def clear(self) -> None:
        """Clear all caches."""
        count = len(self.content_cache)
        self.content_cache.clear()
        self.symbol_cache.clear()
        self.structure_cache.clear()
        self.access_times.clear()
        logger.info("🧹 Cleared cache (%s files)", count)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (
            (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        )

        return {
            **self.stats,
            "cached_files": len(self.content_cache),
            "cached_symbols": len(self.symbol_cache),
            "cached_structures": len(self.structure_cache),
            "hit_rate_percent": round(hit_rate, 1),
            "total_requests": total_requests,
        }
