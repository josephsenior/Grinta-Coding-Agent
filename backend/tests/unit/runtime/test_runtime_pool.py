"""Unit tests for backend.runtime.runtime_pool — RuntimePool, WarmRuntimePool, SingleUseRuntimePool."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.runtime.runtime_pool import (
    PooledRuntime,
    RuntimePool,
    SingleUseRuntimePool,
    WarmPoolPolicy,
    WarmRuntimePool,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_runtime() -> MagicMock:
    rt = MagicMock()
    rt.sid = f"rt-{id(rt)}"
    return rt


def _pooled(rt=None) -> PooledRuntime:
    return PooledRuntime(runtime=rt or _mock_runtime())


# ── PooledRuntime dataclass ──────────────────────────────────────────


class TestPooledRuntime:
    def test_fields(self):
        rt = _mock_runtime()
        pr = PooledRuntime(runtime=rt, repo_directory="/workspace")
        assert pr.runtime is rt
        assert pr.repo_directory == "/workspace"

    def test_default_repo_directory(self):
        pr = PooledRuntime(runtime=_mock_runtime())
        assert pr.repo_directory is None


# ── WarmPoolPolicy ───────────────────────────────────────────────────


class TestWarmPoolPolicy:
    def test_fields(self):
        policy = WarmPoolPolicy(max_size=5, ttl_seconds=300.0)
        assert policy.max_size == 5
        assert policy.ttl_seconds == 300.0


# ── RuntimePool (abstract base) ─────────────────────────────────────


class TestRuntimePoolBase:
    def test_acquire_raises(self):
        pool = RuntimePool()
        with pytest.raises(NotImplementedError):
            pool.acquire("key")

    def test_release_raises(self):
        pool = RuntimePool()
        with pytest.raises(NotImplementedError):
            pool.release("key", _pooled())

    def test_stats_default(self):
        pool = RuntimePool()
        assert pool.stats() == {}

    def test_cleanup_expired_default(self):
        pool = RuntimePool()
        assert pool.cleanup_expired() == 0

    def test_idle_reclaim_stats_default(self):
        pool = RuntimePool()
        assert pool.idle_reclaim_stats() == {}

    def test_eviction_stats_default(self):
        pool = RuntimePool()
        assert pool.eviction_stats() == {}


# ── SingleUseRuntimePool ────────────────────────────────────────────


class TestSingleUseRuntimePool:
    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_acquire_returns_none(self, mock_disconnect):
        pool = SingleUseRuntimePool()
        assert pool.acquire("key") is None

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_release_disconnects(self, mock_disconnect):
        pool = SingleUseRuntimePool()
        rt = _mock_runtime()
        pr = PooledRuntime(runtime=rt)
        pool.release("key", pr)
        mock_disconnect.assert_called_once_with(rt)


# ── WarmRuntimePool ─────────────────────────────────────────────────


class TestWarmRuntimePool:
    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_acquire_empty_returns_none(self, _):
        pool = WarmRuntimePool()
        assert pool.acquire("docker") is None

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_release_and_acquire(self, _):
        pool = WarmRuntimePool(max_size_per_key=2, ttl_seconds=60.0)
        pr = _pooled()
        pool.release("docker", pr)
        acquired = pool.acquire("docker")
        assert acquired is pr

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_fifo_ordering(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pr1 = _pooled()
        pr2 = _pooled()
        pool.release("docker", pr1)
        pool.release("docker", pr2)
        assert pool.acquire("docker") is pr1
        assert pool.acquire("docker") is pr2

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_eviction_when_over_max_size(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=1, ttl_seconds=60.0)
        pr1 = _pooled()
        pr2 = _pooled()
        pool.release("docker", pr1)
        pool.release("docker", pr2)
        # pr1 should be evicted (FIFO)
        mock_disconnect.assert_called_once_with(pr1.runtime)
        assert pool.eviction_stats().get("docker", 0) == 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_stats(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        pool.release("docker", _pooled())
        pool.release("local", _pooled())
        stats = pool.stats()
        assert stats["docker"] == 2
        assert stats["local"] == 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_ttl_expiration_on_acquire(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=0.01)
        pr = _pooled()
        pool.release("docker", pr)
        time.sleep(0.02)  # Wait for TTL to expire
        acquired = pool.acquire("docker")
        assert acquired is None
        mock_disconnect.assert_called_with(pr.runtime)
        assert pool.idle_reclaim_stats().get("docker", 0) >= 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_cleanup_expired(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=0.01)
        pool.release("docker", _pooled())
        pool.release("docker", _pooled())
        time.sleep(0.02)
        removed = pool.cleanup_expired()
        assert removed == 2
        assert pool.stats().get("docker", 0) == 0

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_cleanup_preserves_fresh_entries(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        removed = pool.cleanup_expired()
        assert removed == 0
        assert pool.stats()["docker"] == 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_remove_runtime_found(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        rt = _mock_runtime()
        pr = PooledRuntime(runtime=rt)
        pool.release("docker", pr)
        assert pool.remove_runtime("docker", rt) is True
        mock_disconnect.assert_called_with(rt)
        assert pool.stats().get("docker", 0) == 0

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_remove_runtime_not_found(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        unknown_rt = _mock_runtime()
        assert pool.remove_runtime("docker", unknown_rt) is False
        assert pool.stats()["docker"] == 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_remove_runtime_empty_key(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        assert pool.remove_runtime("docker", _mock_runtime()) is False

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_different_keys_isolated(self, _):
        pool = WarmRuntimePool(max_size_per_key=2, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        pool.release("local", _pooled())
        assert pool.acquire("docker") is not None
        assert pool.acquire("local") is not None
        assert pool.acquire("docker") is None


# ── WarmRuntimePool.configure_policies ───────────────────────────────


class TestConfigurePolicies:
    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_configure_default_policy(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        pool.release("docker", _pooled())
        pool.release("docker", _pooled())

        # Reduce max_size to 1 via configure
        new_policy = WarmPoolPolicy(max_size=1, ttl_seconds=60.0)
        pool.configure_policies(new_policy, {})
        assert pool.stats()["docker"] == 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_configure_zero_max_size_evicts_all(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        pool.release("docker", _pooled())

        new_policy = WarmPoolPolicy(max_size=0, ttl_seconds=60.0)
        pool.configure_policies(new_policy, {})
        assert pool.stats().get("docker", 0) == 0

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_configure_with_overrides(self, _):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())
        pool.release("docker", _pooled())
        pool.release("local", _pooled())

        default = WarmPoolPolicy(max_size=5, ttl_seconds=60.0)
        overrides = {"docker": WarmPoolPolicy(max_size=1, ttl_seconds=60.0)}
        pool.configure_policies(default, overrides)

        # Docker should be trimmed to 1
        assert pool.stats()["docker"] == 1
        # Local should remain at 1 (default allows 5)
        assert pool.stats()["local"] == 1

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_zero_max_acquire_returns_none(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        pool.release("docker", _pooled())

        new_policy = WarmPoolPolicy(max_size=0, ttl_seconds=60.0)
        pool.configure_policies(new_policy, {})
        assert pool.acquire("docker") is None

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_zero_max_release_disconnects(self, mock_disconnect):
        pool = WarmRuntimePool(max_size_per_key=5, ttl_seconds=60.0)
        new_policy = WarmPoolPolicy(max_size=0, ttl_seconds=60.0)
        pool.configure_policies(new_policy, {})

        rt = _mock_runtime()
        pr = PooledRuntime(runtime=rt)
        pool.release("docker", pr)
        mock_disconnect.assert_called_with(rt)


# ── Idle reclaim & eviction counters ─────────────────────────────────


class TestCounters:
    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_initial_counters_empty(self, _):
        pool = WarmRuntimePool()
        assert pool.idle_reclaim_stats() == {}
        assert pool.eviction_stats() == {}

    @patch("backend.runtime.runtime_pool.call_async_disconnect")
    def test_eviction_counter_increments(self, _):
        pool = WarmRuntimePool(max_size_per_key=1, ttl_seconds=60.0)
        pool.release("k", _pooled())
        pool.release("k", _pooled())
        pool.release("k", _pooled())
        assert pool.eviction_stats()["k"] == 2

