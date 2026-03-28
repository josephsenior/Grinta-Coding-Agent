"""Tests for backend.gateway.utils.cache — multi-layer caching."""

from __future__ import annotations

import time
from unittest.mock import patch


from backend.gateway.utils import cache as cache_mod
from backend.gateway.utils.cache import CacheKey


# ---------------------------------------------------------------------------
# CacheKey
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_default_prefix(self):
        key = CacheKey.build("user", "123")
        assert key == "forge:user:123"

    def test_custom_prefix(self):
        key = CacheKey.build("a", "b", prefix="app")
        assert key == "app:a:b"

    def test_single_part(self):
        key = CacheKey.build("only")
        assert key == "forge:only"


# ---------------------------------------------------------------------------
# L1 cache operations (no Redis)
# ---------------------------------------------------------------------------


class TestL1Cache:
    """Tests that exercise get/set/delete/clear on the in-memory L1 layer only."""

    def setup_method(self):
        self._orig = cache_mod._l1_cache.copy()
        cache_mod._l1_cache.clear()

    def teardown_method(self):
        cache_mod._l1_cache.clear()
        cache_mod._l1_cache.update(self._orig)

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_set_and_get(self, _mock_redis):
        cache_mod.cache_set("k1", {"data": 1}, layer="l1")
        result = cache_mod.get("k1")
        assert result == {"data": 1}

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_get_missing_returns_default(self, _mock_redis):
        result = cache_mod.get("no_such_key", default="fallback")
        assert result == "fallback"

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_expired_entry_returns_default(self, _mock_redis):
        # Set with TTL of 0.01s, then wait
        cache_mod.cache_set("k2", "val", ttl=1, layer="l1")
        # Manually expire it
        cache_mod._l1_cache["k2"] = ("val", time.time() - 10)
        result = cache_mod.get("k2", default="gone")
        assert result == "gone"

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_delete(self, _mock_redis):
        cache_mod.cache_set("k3", "val", layer="l1")
        cache_mod.delete("k3", layer="l1")
        assert cache_mod.get("k3") is None

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_clear(self, _mock_redis):
        cache_mod.cache_set("a", 1, layer="l1")
        cache_mod.cache_set("b", 2, layer="l1")
        cache_mod.clear(layer="l1")
        assert cache_mod.get("a") is None
        assert cache_mod.get("b") is None

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_size_limit_eviction(self, _mock_redis):
        original_limit = cache_mod._l1_cache_size_limit
        cache_mod._l1_cache_size_limit = 3
        try:
            for i in range(5):
                cache_mod.cache_set(f"key{i}", i, layer="l1")
            assert len(cache_mod._l1_cache) <= 3
        finally:
            cache_mod._l1_cache_size_limit = original_limit

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_no_ttl_means_no_expiry(self, _mock_redis):
        cache_mod.cache_set("forever", "val", ttl=None, layer="l1")
        val, expiry = cache_mod._l1_cache["forever"]
        assert expiry == 0  # 0 means no expiration


# ---------------------------------------------------------------------------
# @cached decorator
# ---------------------------------------------------------------------------


class TestCachedDecorator:
    def setup_method(self):
        self._orig = cache_mod._l1_cache.copy()
        cache_mod._l1_cache.clear()

    def teardown_method(self):
        cache_mod._l1_cache.clear()
        cache_mod._l1_cache.update(self._orig)

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    async def test_async_cached(self, _mock_redis):
        call_count = 0

        @cache_mod.cached("test", ttl=60)
        async def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = await compute(5)
        result2 = await compute(5)
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # second call served from cache

    @patch.object(cache_mod, "get_redis_client", return_value=None)
    def test_sync_cached(self, _mock_redis):
        call_count = 0

        @cache_mod.cached("test_sync", ttl=60)
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x + 1

        result1 = compute(3)
        result2 = compute(3)
        assert result1 == 4
        assert result2 == 4
        assert call_count == 1
