"""Tests for backend.core.cache.cache_utils — Redis cache utility functions."""

from __future__ import annotations

from types import SimpleNamespace


from backend.core.cache.cache_utils import (
    extract_redis_stats,
    get_redis_connection_params,
    merge_settings_with_cache,
)


# ── extract_redis_stats ──────────────────────────────────────────────


class TestExtractRedisStats:
    def test_basic_extraction(self):
        info = {
            "used_memory": 1024 * 1024 * 10,  # 10 MB
            "total_commands_processed": 500,
            "keyspace_hits": 300,
            "keyspace_misses": 200,
        }
        result = extract_redis_stats(info, ["key1"], ["u1", "u2"])
        assert abs(result["redis_used_memory_mb"] - 10.0) < 0.01
        assert result["redis_total_commands"] == 500
        assert result["redis_keyspace_hits"] == 300
        assert result["redis_keyspace_misses"] == 200
        assert result["global_config_cached"] is True
        assert result["cached_users"] == 2

    def test_empty_keys(self):
        info = {
            "used_memory": 0,
            "total_commands_processed": 0,
            "keyspace_hits": 0,
            "keyspace_misses": 0,
        }
        result = extract_redis_stats(info, [], [])
        assert result["global_config_cached"] is False
        assert result["cached_users"] == 0

    def test_missing_info_keys(self):
        """Missing info keys default to 0."""
        result = extract_redis_stats({}, [], [])
        assert result["redis_used_memory_mb"] == 0.0
        assert result["redis_total_commands"] == 0


# ── merge_settings_with_cache ────────────────────────────────────────


class TestMergeSettingsWithCache:
    def _make_settings(self, val="base"):
        """Create a settings-like object with merge_with_config_settings."""
        s = SimpleNamespace(val=val)
        s.merge_with_config_settings = lambda: SimpleNamespace(val=val + "_merged")
        return s

    def test_merges_when_global_config_present(self):
        settings = self._make_settings("x")
        cache: dict = {}
        result = merge_settings_with_cache(
            "user1", settings, "some-config", cache, 100.0
        )
        assert result.val == "x_merged"
        assert "user1" in cache

    def test_no_merge_when_global_config_none(self):
        settings = self._make_settings("y")
        cache: dict = {}
        result = merge_settings_with_cache("user2", settings, None, cache, 100.0)
        assert result.val == "y"
        assert "user2" in cache

    def test_cache_stores_timestamp(self):
        settings = self._make_settings("z")
        cache: dict = {}
        merge_settings_with_cache("u", settings, None, cache, 42.5)
        _, ts = cache["u"]
        assert ts == 42.5

    def test_lru_eviction_at_256(self):
        cache: dict = {}
        # Fill cache to 256 entries
        for i in range(256):
            cache[f"user_{i}"] = (SimpleNamespace(), float(i))
        assert len(cache) == 256

        settings = self._make_settings("new")
        merge_settings_with_cache("new_user", settings, None, cache, 999.0)
        # One old entry should have been evicted, new one added
        assert "new_user" in cache
        assert len(cache) == 256  # Still 256, one evicted + one added

    def test_existing_user_not_evicted(self):
        cache: dict = {}
        for i in range(256):
            cache[f"user_{i}"] = (SimpleNamespace(), float(i))

        # Update existing user — no eviction needed
        settings = self._make_settings("upd")
        merge_settings_with_cache("user_0", settings, None, cache, 999.0)
        assert len(cache) == 256


# ── get_redis_connection_params ──────────────────────────────────────


class TestGetRedisConnectionParams:
    def test_returns_dict(self):
        result = get_redis_connection_params("localhost", 6379)
        assert isinstance(result, dict)

    def test_required_keys(self):
        result = get_redis_connection_params("localhost", 6379, password="pw")
        assert result["decode_responses"] is False
        assert result["socket_connect_timeout"] == 5
        assert result["socket_timeout"] == 10
        assert result["retry_on_timeout"] is True
        assert result["health_check_interval"] == 30

    def test_password_param_ignored(self):
        """The function doesn't use password in output (the caller adds it)."""
        r1 = get_redis_connection_params("h", 1, password="x")
        r2 = get_redis_connection_params("h", 1, password=None)
        assert r1 == r2
