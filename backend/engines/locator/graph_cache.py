"""Graph Caching System - Fast Code Graph Access.

Caches built code graphs to avoid expensive rebuilding.
Incremental updates on file changes.

Supports both local (single-instance) and distributed (Redis, multi-instance) modes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

from backend.core.logger import FORGE_logger as logger

from backend.core.cache.factory import create_distributed_cache


class GraphCache:
    """Caches code graphs for fast access.

    Features:
    - Caches entire graph structure
    - Tracks file modifications
    - Incremental updates (only rebuild changed parts)
    - Persistent storage
    - TTL-based expiration
    """

    def __init__(
        self,
        cache_dir: str = "./.Forge/graph_cache",
        ttl_seconds: int = 3600,  # 1 hour
        enable_persistence: bool = True,
        use_distributed: bool = True,  # Use Redis if available
    ):
        """Initialize graph cache with optional distributed (Redis) backend.

        Args:
            cache_dir: Directory to store cached graphs
            ttl_seconds: Time-to-live for cached graphs
            enable_persistence: Persist to disk
            use_distributed: Use Redis distributed cache if available (recommended for 1000+ users)

        """
        self.cache_dir = cache_dir
        self.ttl = timedelta(seconds=ttl_seconds)
        self.enable_persistence = enable_persistence

        # Try to use distributed cache if requested and available
        self.distributed_cache = None
        if use_distributed:
            self.distributed_cache = create_distributed_cache(
                prefix="forge:graph_cache",
                ttl_seconds=ttl_seconds,
            )
            if self.distributed_cache:
                logger.info(
                    "📊 Graph cache using REDIS distributed backend (perfect for 1000+ users!)"
                )

        # In-memory cache (L1)
        self.graph_cache: dict[str, Any] = {}  # repo_path → graph_data
        self.graph_metadata: dict[str, dict[str, Any]] = {}  # repo_path → metadata
        self.file_mtimes: dict[
            str, dict[str, float]
        ] = {}  # repo_path → {file_path: mtime}

        # Stats
        self.stats = {
            "hits": 0,
            "misses": 0,
            "partial_updates": 0,
            "full_rebuilds": 0,
            "files_tracked": 0,
            "distributed_hits": 0,
            "distributed_misses": 0,
        }

        # Create cache directory
        if enable_persistence:
            os.makedirs(cache_dir, exist_ok=True)

        cache_mode = "distributed (Redis)" if self.distributed_cache else "local"
        logger.info(
            "📊 Graph cache initialized (mode=%s, ttl=%ss)", cache_mode, ttl_seconds
        )

    def _load_from_persistence(self, repo_path: str) -> None:
        """Load graph from disk persistence if enabled.

        Args:
            repo_path: Path to repository

        """
        if self.enable_persistence:
            self._load_from_disk(repo_path)

    def _load_from_distributed_cache(self, repo_path: str) -> bool:
        """Load graph from distributed cache (L2).

        Args:
            repo_path: Path to repository

        Returns:
            True if loaded successfully, False otherwise

        """
        if not self.distributed_cache:
            return False

        try:
            cached_data = self.distributed_cache.get(repo_path)
            if cached_data:
                self.graph_cache[repo_path] = cached_data["graph"]
                self.graph_metadata[repo_path] = cached_data["metadata"]
                self.file_mtimes[repo_path] = cached_data.get("file_mtimes", {})
                self.stats["distributed_hits"] += 1
                self.stats["hits"] += 1
                logger.debug("📊 Graph cache HIT (Redis) for %s", repo_path)
                return True
            self.stats["distributed_misses"] += 1
        except Exception as e:
            logger.debug("Distributed cache error: %s", e)

        return False

    def _validate_cache_entry(self, repo_path: str) -> bool:
        """Validate cached graph entry (TTL and modifications).

        Args:
            repo_path: Path to repository

        Returns:
            True if cache entry is valid, False otherwise

        """
        metadata = self.graph_metadata.get(repo_path, {})
        cached_at = metadata.get("cached_at")

        if cached_at and datetime.now() - cached_at > self.ttl:
            self._invalidate_repo(repo_path)
            self.stats["misses"] += 1
            return False

        if self._has_modifications(repo_path):
            self.stats["partial_updates"] += 1
            logger.debug("⚠️  Graph cache outdated for %s (files modified)", repo_path)
            return False

        return True

    def get_graph(self, repo_path: str) -> Any | None:
        """Get cached graph with 2-tier caching (L1 local, L2 Redis).

        Args:
            repo_path: Path to repository

        Returns:
            Graph data if cached and valid, None otherwise

        """
        # L1: Check in-memory cache (fastest)
        if repo_path not in self.graph_cache:
            self._load_from_persistence(repo_path)

        # L2: Check distributed cache if L1 missed
        if repo_path not in self.graph_cache:
            if self._load_from_distributed_cache(repo_path):
                return self.graph_cache[repo_path]
            self.stats["misses"] += 1
            return None

        # Validate cache entry
        if not self._validate_cache_entry(repo_path):
            return None

        # Cache hit!
        self.stats["hits"] += 1
        logger.debug("✓ Graph cache hit for %s", repo_path)
        return self.graph_cache[repo_path]

    def cache_graph(
        self, repo_path: str, graph_data: Any, tracked_files: set[str] | None = None
    ) -> None:
        """Cache graph for a repository.

        Args:
            repo_path: Path to repository
            graph_data: The graph data to cache
            tracked_files: Set of files included in graph

        """
        # Store graph
        self.graph_cache[repo_path] = graph_data

        # Store metadata
        self.graph_metadata[repo_path] = {
            "cached_at": datetime.now(),
            "file_count": len(tracked_files) if tracked_files else 0,
        }

        # Track file modification times
        if tracked_files:
            self.file_mtimes[repo_path] = {}
            for file_path in tracked_files:
                try:
                    self.file_mtimes[repo_path][file_path] = os.path.getmtime(file_path)
                except (OSError, FileNotFoundError):
                    pass

            self.stats["files_tracked"] = len(tracked_files)

        # Persist to disk (L3 - local persistence)
        if self.enable_persistence:
            self._save_to_disk(repo_path)

        # Store in distributed cache (L2 - shared across instances)
        if self.distributed_cache:
            try:
                cache_data = {
                    "graph": graph_data,
                    "metadata": self.graph_metadata[repo_path],
                    "file_mtimes": self.file_mtimes.get(repo_path, {}),
                }
                self.distributed_cache.set(repo_path, cache_data)
                logger.debug("📊 Stored graph in Redis for %s", repo_path)
            except Exception as e:
                logger.debug("Failed to cache graph in Redis: %s", e)

        logger.info(
            "💾 Cached graph for %s (%s files)", repo_path, self.stats["files_tracked"]
        )

    def _has_modifications(self, repo_path: str) -> bool:
        """Check if any tracked files were modified."""
        if repo_path not in self.file_mtimes:
            return False

        for file_path, cached_mtime in self.file_mtimes[repo_path].items():
            try:
                current_mtime = os.path.getmtime(file_path)
                if current_mtime != cached_mtime:
                    logger.debug("📝 File modified: %s", file_path)
                    return True
            except (OSError, FileNotFoundError):
                # File deleted
                return True

        return False

    def _invalidate_repo(self, repo_path: str) -> None:
        """Invalidate cached graph for a repository."""
        self.graph_cache.pop(repo_path, None)
        self.graph_metadata.pop(repo_path, None)
        self.file_mtimes.pop(repo_path, None)
        logger.debug("🗑️  Invalidated graph cache: %s", repo_path)

    def _get_cache_file_path(self, repo_path: str) -> str:
        """Get cache file path for a repository."""
        # Create safe filename from repo path
        safe_name = repo_path.replace("/", "_").replace("\\", "_").replace(":", "_")
        return os.path.join(self.cache_dir, f"graph_{safe_name}.json")

    def _save_to_disk(self, repo_path: str) -> None:
        """Save graph to disk."""
        try:
            cache_file = self._get_cache_file_path(repo_path)

            metadata_candidate = self.graph_metadata.get(repo_path, {})
            # Copy so we don't mutate the in-memory metadata (cached_at
            # must stay a datetime for _validate_cache_entry arithmetic).
            metadata = dict(
                metadata_candidate if isinstance(metadata_candidate, dict) else {}
            )

            cached_at_value = metadata.get("cached_at")
            if isinstance(cached_at_value, datetime):
                metadata["cached_at"] = cached_at_value.isoformat()

            data = {
                "graph": self.graph_cache.get(repo_path),
                "metadata": metadata,
                "file_mtimes": self.file_mtimes.get(repo_path, {}),
            }

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.debug("💾 Saved graph to %s", cache_file)

        except Exception as e:
            logger.warning("Failed to save graph cache: %s", e)

    def _load_from_disk(self, repo_path: str) -> None:
        """Load graph from disk."""
        try:
            cache_file = self._get_cache_file_path(repo_path)

            if not os.path.exists(cache_file):
                return

            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)

            self.graph_cache[repo_path] = data.get("graph")
            self.file_mtimes[repo_path] = data.get("file_mtimes", {})

            # Convert ISO format back to datetime
            metadata = data.get("metadata", {})
            if "cached_at" in metadata:
                metadata["cached_at"] = datetime.fromisoformat(metadata["cached_at"])
            self.graph_metadata[repo_path] = metadata

            logger.debug("📂 Loaded graph from %s", cache_file)

        except Exception as e:
            logger.warning("Failed to load graph cache: %s", e)

    def clear(self) -> None:
        """Clear all caches."""
        count = len(self.graph_cache)
        self.graph_cache.clear()
        self.graph_metadata.clear()
        self.file_mtimes.clear()
        logger.info("🧹 Cleared graph cache (%s repos)", count)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (
            (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        )

        return {
            **self.stats,
            "cached_repos": len(self.graph_cache),
            "hit_rate_percent": round(hit_rate, 1),
            "total_requests": total_requests,
        }
