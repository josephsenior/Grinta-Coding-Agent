"""Tests for backend.engines.locator.graph_cache — GraphCache."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pytest

from backend.engines.locator.graph_cache import GraphCache


@pytest.fixture
def cache(tmp_path):
    """Create a GraphCache with local-only mode in a temp directory."""
    return GraphCache(
        cache_dir=str(tmp_path / "graph_cache"),
        ttl_seconds=3600,
        enable_persistence=True,
        use_distributed=False,  # No Redis for unit tests
    )


# ===================================================================
# Initialization
# ===================================================================


class TestGraphCacheInit:
    def test_local_mode(self, tmp_path):
        gc = GraphCache(
            cache_dir=str(tmp_path / "gc"),
            use_distributed=False,
        )
        assert gc.distributed_cache is None
        assert gc.stats["hits"] == 0
        assert gc.stats["misses"] == 0

    def test_persistence_creates_dir(self, tmp_path):
        cache_dir = str(tmp_path / "new_dir")
        assert not os.path.exists(cache_dir)
        GraphCache(cache_dir=cache_dir, enable_persistence=True, use_distributed=False)
        assert os.path.isdir(cache_dir)


# ===================================================================
# get_graph / cache_graph
# ===================================================================


class TestGraphCacheGetSet:
    def test_miss_returns_none(self, cache):
        assert cache.get_graph("/repo/path") is None
        assert cache.stats["misses"] == 1

    def test_cache_and_get(self, cache):
        graph_data = {"nodes": [1, 2, 3], "edges": [(1, 2)]}
        cache.cache_graph("/repo", graph_data)
        result = cache.get_graph("/repo")
        assert result == graph_data
        assert cache.stats["hits"] >= 1

    def test_cached_at_stays_datetime_after_save(self, cache):
        """Regression: _save_to_disk must not mutate in-memory cached_at to string."""
        cache.cache_graph("/repo", {"x": 1})
        meta = cache.graph_metadata["/repo"]
        assert isinstance(meta["cached_at"], datetime), (
            "_save_to_disk should not mutate in-memory cached_at to string"
        )

    def test_cache_with_tracked_files(self, cache, tmp_path):
        # Create a real file to track
        f = tmp_path / "main.py"
        f.write_text("print('hello')")
        graph_data = {"nodes": ["main.py"]}
        cache.cache_graph("/repo", graph_data, tracked_files={str(f)})
        assert str(f) in cache.file_mtimes.get("/repo", {})


# ===================================================================
# TTL expiration
# ===================================================================


class TestTTLExpiration:
    def test_expired_entry_returns_none(self, cache):
        graph_data = {"x": 1}
        cache.cache_graph("/repo", graph_data)
        # Backdate cached_at to exceed TTL
        cache.graph_metadata["/repo"]["cached_at"] = datetime.now() - timedelta(hours=2)
        result = cache.get_graph("/repo")
        assert result is None
        assert cache.stats["misses"] >= 1


# ===================================================================
# File modification detection
# ===================================================================


class TestFileModification:
    def test_unmodified_file(self, cache, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        cache.cache_graph("/repo", {"g": True}, tracked_files={str(f)})
        assert cache._has_modifications("/repo") is False

    def test_modified_file(self, cache, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        cache.cache_graph("/repo", {"g": True}, tracked_files={str(f)})
        # Modify the file
        time.sleep(0.01)
        f.write_text("x = 2")
        assert cache._has_modifications("/repo") is True

    def test_deleted_file(self, cache, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        cache.cache_graph("/repo", {"g": True}, tracked_files={str(f)})
        f.unlink()
        assert cache._has_modifications("/repo") is True

    def test_no_tracked_files(self, cache):
        assert cache._has_modifications("/repo") is False


# ===================================================================
# Disk persistence
# ===================================================================


class TestDiskPersistence:
    def test_save_and_load(self, cache):
        graph_data = {"nodes": [1, 2]}
        cache.cache_graph("/my/repo", graph_data)
        # Clear in-memory caches
        cache.graph_cache.clear()
        cache.graph_metadata.clear()
        cache.file_mtimes.clear()
        # Load from disk
        cache._load_from_disk("/my/repo")
        assert cache.graph_cache.get("/my/repo") == graph_data

    def test_load_nonexistent(self, cache):
        # Should not raise
        cache._load_from_disk("/nonexistent")
        assert "/nonexistent" not in cache.graph_cache

    def test_get_cache_file_path(self, cache):
        path = cache._get_cache_file_path("/home/user/repo")
        assert "graph_" in path
        assert path.endswith(".json")
        # Should not contain path separators from repo_path
        basename = os.path.basename(path)
        assert "/" not in basename


# ===================================================================
# Invalidation & clear
# ===================================================================


class TestInvalidation:
    def test_invalidate_repo(self, cache):
        cache.cache_graph("/repo", {"x": 1})
        cache._invalidate_repo("/repo")
        assert "/repo" not in cache.graph_cache
        assert "/repo" not in cache.graph_metadata
        assert "/repo" not in cache.file_mtimes

    def test_clear_all(self, cache):
        cache.cache_graph("/r1", {"a": 1})
        cache.cache_graph("/r2", {"b": 2})
        cache.clear()
        assert not cache.graph_cache
        assert not cache.graph_metadata


# ===================================================================
# Stats
# ===================================================================


class TestGraphCacheStats:
    def test_stats_initial(self, cache):
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate_percent"] == 0
        assert stats["cached_repos"] == 0

    def test_stats_after_operations(self, cache):
        cache.cache_graph("/repo", {"x": 1})
        cache.get_graph("/repo")  # hit
        cache.get_graph("/missing")  # miss
        stats = cache.get_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1
        assert stats["total_requests"] >= 2
        assert stats["cached_repos"] == 1
