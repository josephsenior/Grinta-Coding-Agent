"""Unit tests for backend.core.cache.utils — Redis cache utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.cache.utils import (
    extract_redis_stats,
    merge_settings_with_cache,
    get_redis_connection_params,
)


class TestExtractRedisStats:
    """Tests for extract_redis_stats function."""

    def test_extract_basic_stats(self):
        """Test extracting basic Redis stats."""
        info = {
            "used_memory": 1024 * 1024,  # 1 MB
            "total_commands_processed": 1000,
            "keyspace_hits": 800,
            "keyspace_misses": 200,
        }
        global_keys = ["config"]
        user_keys = ["user1", "user2"]

        result = extract_redis_stats(info, global_keys, user_keys)

        assert result["redis_used_memory_mb"] == 1.0
        assert result["redis_total_commands"] == 1000
        assert result["redis_keyspace_hits"] == 800
        assert result["redis_keyspace_misses"] == 200
        assert result["global_config_cached"] is True
        assert result["cached_users"] == 2

    def test_extract_empty_info(self):
        """Test extracting stats from empty info dict."""
        info = {}
        global_keys = []
        user_keys = []

        result = extract_redis_stats(info, global_keys, user_keys)

        assert result["redis_used_memory_mb"] == 0.0
        assert result["redis_total_commands"] == 0
        assert result["redis_keyspace_hits"] == 0
        assert result["redis_keyspace_misses"] == 0
        assert result["global_config_cached"] is False
        assert result["cached_users"] == 0

    def test_extract_no_global_config(self):
        """Test when no global config is cached."""
        info = {"used_memory": 2 * 1024 * 1024}
        global_keys = []
        user_keys = ["user1", "user2", "user3"]

        result = extract_redis_stats(info, global_keys, user_keys)

        assert result["redis_used_memory_mb"] == 2.0
        assert result["global_config_cached"] is False
        assert result["cached_users"] == 3

    def test_extract_large_memory_usage(self):
        """Test with large memory usage."""
        info = {"used_memory": 512 * 1024 * 1024}  # 512 MB
        global_keys = ["config"]
        user_keys = []

        result = extract_redis_stats(info, global_keys, user_keys)

        assert result["redis_used_memory_mb"] == 512.0

    def test_extract_high_command_count(self):
        """Test with high command count."""
        info = {"total_commands_processed": 1000000}
        global_keys = []
        user_keys = []

        result = extract_redis_stats(info, global_keys, user_keys)

        assert result["redis_total_commands"] == 1000000

    def test_extract_hit_miss_ratio(self):
        """Test extracting hit/miss stats."""
        info = {
            "keyspace_hits": 9000,
            "keyspace_misses": 1000,
        }
        global_keys = []
        user_keys = []

        result = extract_redis_stats(info, global_keys, user_keys)

        assert result["redis_keyspace_hits"] == 9000
        assert result["redis_keyspace_misses"] == 1000
        # 90% hit rate
        hit_rate = 9000 / (9000 + 1000)
        assert hit_rate == 0.9


class TestMergeSettingsWithCache:
    """Tests for merge_settings_with_cache function."""

    def test_merge_with_global_config(self):
        """Test merging settings when global config exists."""
        user_id = "user1"
        settings = MagicMock()
        settings.merge_with_config_settings.return_value = MagicMock(name="merged")

        global_config = {"key": "value"}
        cache = {}
        current_time = 1000.0

        result = merge_settings_with_cache(user_id, settings, global_config, cache, current_time)

        # Should call merge_with_config_settings
        settings.merge_with_config_settings.assert_called_once()
        assert result == settings.merge_with_config_settings.return_value
        # Should add to cache
        assert user_id in cache
        assert cache[user_id][1] == current_time

    def test_merge_without_global_config(self):
        """Test merging settings when no global config."""
        user_id = "user1"
        settings = MagicMock()
        global_config = None
        cache = {}
        current_time = 1000.0

        result = merge_settings_with_cache(user_id, settings, global_config, cache, current_time)

        # Should return settings as-is
        assert result == settings
        # Should not call merge method
        settings.merge_with_config_settings.assert_not_called()

    def test_cache_stores_merged_settings(self):
        """Test that cache stores merged settings."""
        user_id = "user1"
        settings = MagicMock()
        merged = MagicMock(name="merged")
        settings.merge_with_config_settings.return_value = merged

        global_config = {"key": "value"}
        cache = {}
        current_time = 1000.0

        merge_settings_with_cache(user_id, settings, global_config, cache, current_time)

        cached_settings, cached_time = cache[user_id]
        assert cached_settings == merged
        assert cached_time == 1000.0

    def test_cache_evicts_oldest_when_full(self):
        """Test that cache evicts oldest entry when full (>256 users)."""
        # Create cache with 256 entries
        cache = {f"user{i}": (MagicMock(), float(i)) for i in range(256)}

        # Add new user - should evict oldest (user0)
        settings = MagicMock()
        settings.merge_with_config_settings.return_value = MagicMock()

        merge_settings_with_cache(
            "new_user", settings, {"config": True}, cache, 300.0
        )

        # Cache should still have 256 entries
        assert len(cache) == 256
        # Oldest user should be evicted
        assert "user0" not in cache
        # New user should be added
        assert "new_user" in cache

    def test_cache_doesnt_evict_if_user_exists(self):
        """Test that cache doesn't evict when updating existing user."""
        cache = {f"user{i}": (MagicMock(), float(i)) for i in range(256)}

        # Update existing user
        settings = MagicMock()
        settings.merge_with_config_settings.return_value = MagicMock()
        original_count = len(cache)

        merge_settings_with_cache(
            "user0", settings, {"config": True}, cache, 300.0
        )

        # Cache count should not change
        assert len(cache) == original_count
        # user0 should still exist with updated time
        assert cache["user0"][1] == 300.0

    def test_multiple_users_in_cache(self):
        """Test cache with multiple users."""
        cache = {}

        for i in range(5):
            user_id = f"user{i}"
            settings = MagicMock()
            settings.merge_with_config_settings.return_value = MagicMock()

            merge_settings_with_cache(
                user_id, settings, None, cache, float(i)
            )

        assert len(cache) == 5
        assert all(f"user{i}" in cache for i in range(5))

    def test_cache_timestamp_precision(self):
        """Test that cache preserves timestamp precision."""
        cache = {}
        current_time = 1234567890.123456

        settings = MagicMock()
        settings.merge_with_config_settings.return_value = MagicMock()

        merge_settings_with_cache("user1", settings, None, cache, current_time)

        _, cached_time = cache["user1"]
        assert cached_time == current_time


class TestGetRedisConnectionParams:
    """Tests for get_redis_connection_params function."""

    def test_basic_params(self):
        """Test getting basic connection parameters."""
        params = get_redis_connection_params("localhost", 6379)

        assert params["decode_responses"] is False
        assert params["socket_connect_timeout"] == 5
        assert params["socket_timeout"] == 10
        assert params["retry_on_timeout"] is True
        assert params["health_check_interval"] == 30

    def test_params_with_password(self):
        """Test getting parameters with password."""
        params = get_redis_connection_params("localhost", 6379, "secret")

        # Should return params regardless of password
        assert isinstance(params, dict)
        assert params["socket_connect_timeout"] == 5

    def test_params_with_custom_host(self):
        """Test getting parameters with custom host."""
        params = get_redis_connection_params("redis.example.com", 6380)

        assert isinstance(params, dict)
        assert params["socket_connect_timeout"] == 5

    def test_params_with_custom_port(self):
        """Test getting parameters with custom port."""
        params = get_redis_connection_params("localhost", 6380)

        assert isinstance(params, dict)
        assert params["socket_timeout"] == 10

    def test_params_structure(self):
        """Test that parameters have expected keys."""
        params = get_redis_connection_params("host", 1234)

        expected_keys = {
            "decode_responses",
            "socket_connect_timeout",
            "socket_timeout",
            "retry_on_timeout",
            "health_check_interval",
        }
        assert set(params.keys()) == expected_keys

    def test_params_immutability(self):
        """Test that multiple calls return consistent values."""
        params1 = get_redis_connection_params("localhost", 6379)
        params2 = get_redis_connection_params("localhost", 6379)

        assert params1 == params2

    def test_timeout_values(self):
        """Test that timeout values are reasonable."""
        params = get_redis_connection_params("localhost", 6379)

        # Timeouts should be positive integers
        assert params["socket_connect_timeout"] > 0
        assert params["socket_timeout"] > 0
        # Health check interval should be longer than socket timeout
        assert params["health_check_interval"] > params["socket_timeout"]

    def test_retry_is_enabled(self):
        """Test that retry on timeout is enabled."""
        params = get_redis_connection_params("localhost", 6379)

        assert params["retry_on_timeout"] is True

    def test_decode_responses_disabled(self):
        """Test that decode_responses is disabled by default."""
        params = get_redis_connection_params("localhost", 6379)

        assert params["decode_responses"] is False


class TestIntegration:
    """Integration tests for cache utilities."""

    def test_extract_and_merge_together(self):
        """Test using extract and merge utilities together."""
        # Extract stats
        info = {
            "used_memory": 2 * 1024 * 1024,
            "total_commands_processed": 5000,
            "keyspace_hits": 4500,
            "keyspace_misses": 500,
        }
        stats = extract_redis_stats(info, ["global"], ["user1", "user2"])

        assert stats["redis_used_memory_mb"] == 2.0
        assert stats["cached_users"] == 2

    def test_connection_params_with_different_hosts(self):
        """Test connection parameters with various hosts."""
        hosts = [
            "localhost",
            "127.0.0.1",
            "redis.example.com",
            "redis-prod.aws.com",
        ]

        for host in hosts:
            params = get_redis_connection_params(host, 6379)
            assert params["socket_connect_timeout"] == 5
            assert params["retry_on_timeout"] is True

    def test_connection_params_with_different_ports(self):
        """Test connection parameters with various ports."""
        ports = [6379, 6380, 26379, 9999]

        for port in ports:
            params = get_redis_connection_params("localhost", port)
            assert params["socket_timeout"] == 10
            assert params["health_check_interval"] == 30
