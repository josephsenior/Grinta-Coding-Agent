"""Tests for backend.core.cache.redis_cache — DistributedCache local-fallback path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.cache.redis_cache import DistributedCache


# ---------------------------------------------------------------------------
# Test the local-fallback path (no Redis available)
# ---------------------------------------------------------------------------
@pytest.fixture
def cache():
    """Create a DistributedCache that always falls back to local dict."""
    with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", False):
        c = DistributedCache(prefix="test", ttl_seconds=60)
        assert not c.enabled
        yield c


class TestDistributedCacheLocalFallback:
    # --- basic CRUD ---
    def test_get_miss(self, cache):
        assert cache.get("no-key") is None
        assert cache.stats["misses"] == 1

    def test_set_and_get(self, cache):
        assert cache.set("k1", {"a": 1}) is True
        assert cache.get("k1") == {"a": 1}
        assert cache.stats["hits"] == 1
        assert cache.stats["sets"] == 1

    def test_delete_existing(self, cache):
        cache.set("k1", "v1")
        assert cache.delete("k1") is True
        assert cache.stats["deletes"] == 1
        assert cache.get("k1") is None

    def test_delete_missing(self, cache):
        assert cache.delete("nope") is False

    def test_exists(self, cache):
        assert cache.exists("k1") is False
        cache.set("k1", 42)
        assert cache.exists("k1") is True

    def test_clear(self, cache):
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.clear() is True
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_get_size(self, cache):
        assert cache.get_size() == 0
        cache.set("k", "v")
        assert cache.get_size() == 1

    def test_get_stats(self, cache):
        cache.set("k", "v")
        cache.get("k")
        cache.get("miss")
        stats = cache.get_stats()
        assert stats["backend"] == "local"
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["sets"] == 1
        assert stats["total_requests"] == 2
        assert stats["hit_rate_percent"] == 50.0

    def test_get_stats_zero_requests(self, cache):
        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.0

    def test_close_noop(self, cache):
        cache.close()  # Should not raise


# ---------------------------------------------------------------------------
# _make_key
# ---------------------------------------------------------------------------
class TestMakeKey:
    def test_prefixed(self):
        with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", False):
            c = DistributedCache(prefix="myapp")
            assert c._make_key("session:123") == "myapp:session:123"


# ---------------------------------------------------------------------------
# Redis-enabled path (mocked Redis client)
# ---------------------------------------------------------------------------
class TestDistributedCacheRedisPath:
    @pytest.fixture
    def redis_cache(self):
        """DistributedCache with a mocked Redis client."""
        with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", True):
            c = DistributedCache.__new__(DistributedCache)
            c.prefix = "test"
            c.ttl_seconds = 60
            c.enabled = True
            c.client = MagicMock()
            c._local_fallback = {}
            c.stats = {"hits": 0, "misses": 0, "sets": 0, "deletes": 0, "errors": 0}
            yield c

    def test_get_hit(self, redis_cache):
        import json

        redis_cache.client.get.return_value = json.dumps({"x": 1}).encode("utf-8")
        assert redis_cache.get("k") == {"x": 1}
        assert redis_cache.stats["hits"] == 1

    def test_get_miss(self, redis_cache):
        redis_cache.client.get.return_value = None
        assert redis_cache.get("k") is None
        assert redis_cache.stats["misses"] == 1

    def test_get_invalid_json(self, redis_cache):
        redis_cache.client.get.return_value = b"not-json"
        assert redis_cache.get("k") is None
        assert redis_cache.stats["misses"] >= 1

    def test_get_redis_error(self, redis_cache):
        redis_cache.client.get.side_effect = Exception("connection lost")
        assert redis_cache.get("k") is None
        assert redis_cache.stats["errors"] == 1

    def test_set_success(self, redis_cache):
        assert redis_cache.set("k", [1, 2, 3]) is True
        redis_cache.client.setex.assert_called_once()
        assert redis_cache.stats["sets"] == 1

    def test_set_redis_error(self, redis_cache):
        redis_cache.client.setex.side_effect = Exception("timeout")
        assert redis_cache.set("k", "v") is False
        assert redis_cache.stats["errors"] == 1

    def test_delete_success(self, redis_cache):
        redis_cache.client.delete.return_value = 1
        assert redis_cache.delete("k") is True

    def test_delete_miss(self, redis_cache):
        redis_cache.client.delete.return_value = 0
        assert redis_cache.delete("k") is False

    def test_exists_true(self, redis_cache):
        redis_cache.client.exists.return_value = 1
        assert redis_cache.exists("k") is True

    def test_exists_false(self, redis_cache):
        redis_cache.client.exists.return_value = 0
        assert redis_cache.exists("k") is False

    def test_clear(self, redis_cache):
        redis_cache.client.scan.return_value = (0, [b"test:k1", b"test:k2"])
        redis_cache.client.delete.return_value = 2
        assert redis_cache.clear() is True

    def test_get_size(self, redis_cache):
        redis_cache.client.scan_iter.return_value = iter([b"k1", b"k2", b"k3"])
        assert redis_cache.get_size() == 3

    def test_close(self, redis_cache):
        redis_cache.close()
        redis_cache.client.close.assert_called_once()

    def test_delete_error(self, redis_cache):
        """Test exception handling in delete()."""
        redis_cache.client.delete.side_effect = Exception("delete failed")
        assert redis_cache.delete("k") is False
        assert redis_cache.stats["errors"] == 1

    def test_close_error(self, redis_cache):
        """Test exception handling in close()."""
        redis_cache.client.close.side_effect = Exception("close failed")
        redis_cache.close()  # Should not raise, just log error


class TestDistributedCacheInit:
    def test_init_without_host_env(self, monkeypatch):
        monkeypatch.delenv("REDIS_HOST", raising=False)
        with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", True):
            cache = DistributedCache(prefix="test")
        assert cache.enabled is False
        assert cache.client is None

    def test_init_with_connection_error(self, monkeypatch):
        monkeypatch.setenv("REDIS_HOST", "redis")
        with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", True):
            with patch(
                "backend.core.cache.redis_cache.ConnectionPool",
                side_effect=Exception("boom"),
            ):
                cache = DistributedCache(prefix="test")
        assert cache.enabled is False
        assert cache.client is None

    def test_init_successful_connection(self, monkeypatch):
        """Test successful Redis connection initialization."""
        monkeypatch.setenv("REDIS_HOST", "localhost")
        with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", True):
            mock_pool = MagicMock()
            mock_redis = MagicMock()
            mock_redis.ping.return_value = True

            with patch(
                "backend.core.cache.redis_cache.ConnectionPool", return_value=mock_pool
            ):
                with patch(
                    "backend.core.cache.redis_cache.Redis", return_value=mock_redis
                ):
                    cache = DistributedCache(prefix="test", host="localhost")

            assert cache.enabled is True
            assert cache.client is not None
            mock_redis.ping.assert_called_once()


class TestDistributedCacheRedisEdgeCases:
    @pytest.fixture
    def redis_cache(self):
        with patch("backend.core.cache.redis_cache.REDIS_AVAILABLE", True):
            c = DistributedCache.__new__(DistributedCache)
            c.prefix = "test"
            c.ttl_seconds = 60
            c.enabled = True
            c.client = MagicMock()
            c._local_fallback = {}
            c.stats = {"hits": 0, "misses": 0, "sets": 0, "deletes": 0, "errors": 0}
            yield c

    def test_set_json_serialization_failure(self, redis_cache):
        # Create a circular reference which will fail JSON serialization
        circular = {}
        circular["self"] = circular

        # Even with _json_fallback, deeply nested circular refs will fail
        with patch(
            "backend.core.cache.redis_cache.json.dumps",
            side_effect=TypeError("circular"),
        ):
            assert redis_cache.set("k", {"data": "test"}) is False
            redis_cache.client.setex.assert_not_called()

    def test_clear_handles_redis_error(self, redis_cache):
        redis_cache.client.scan.side_effect = Exception("bad")
        assert redis_cache.clear() is False
        assert redis_cache.stats["errors"] == 1

    def test_exists_handles_redis_error(self, redis_cache):
        redis_cache.client.exists.side_effect = Exception("bad")
        assert redis_cache.exists("k") is False

    def test_get_stats_redis_success(self, redis_cache):
        redis_cache.client.info.side_effect = [
            {"total_commands_processed": 5, "keyspace_hits": 2, "keyspace_misses": 3},
            {"used_memory": 1024, "maxmemory": 2048},
        ]
        stats = redis_cache.get_stats()
        assert stats["redis_total_commands"] == 5
        assert stats["redis_used_memory_mb"] == 1024 / (1024 * 1024)

    def test_get_stats_redis_error(self, redis_cache):
        redis_cache.client.info.side_effect = Exception("bad")
        stats = redis_cache.get_stats()
        assert stats["backend"] == "redis"

    def test_get_size_handles_redis_error(self, redis_cache):
        redis_cache.client.scan_iter.side_effect = Exception("bad")
        assert redis_cache.get_size() == 0
