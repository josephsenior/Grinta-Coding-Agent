"""Tests for RuntimeOrchestrator."""

import unittest
from unittest.mock import MagicMock, patch

from backend.runtime.orchestrator import (
    RuntimeOrchestrator,
    RuntimeAcquireResult,
)
from backend.runtime.runtime_pool import PooledRuntime, WarmPoolPolicy


class TestRuntimeAcquireResult(unittest.TestCase):
    """Test RuntimeAcquireResult dataclass."""

    def test_runtime_acquire_result_creation(self):
        """Test creating RuntimeAcquireResult."""
        mock_runtime = MagicMock()

        result = RuntimeAcquireResult(
            runtime=mock_runtime, repo_directory="/path/to/repo"
        )

        self.assertEqual(result.runtime, mock_runtime)
        self.assertEqual(result.repo_directory, "/path/to/repo")

    def test_runtime_acquire_result_no_repo(self):
        """Test RuntimeAcquireResult without repo directory."""
        mock_runtime = MagicMock()

        result = RuntimeAcquireResult(runtime=mock_runtime)

        self.assertEqual(result.runtime, mock_runtime)
        self.assertIsNone(result.repo_directory)


class TestRuntimeOrchestrator(unittest.TestCase):
    """Test RuntimeOrchestrator runtime pooling."""

    def setUp(self):
        """Create mock pool and telemetry for testing."""
        self.mock_pool = MagicMock()
        self.mock_pool.stats.return_value = {}
        self.mock_pool.idle_reclaim_stats.return_value = {}
        self.mock_pool.eviction_stats.return_value = {}

        self.mock_telemetry = MagicMock()

        self.orchestrator = RuntimeOrchestrator(
            pool=self.mock_pool, telemetry=self.mock_telemetry
        )

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    def test_init_default_pool(self, mock_watchdog):
        """Test RuntimeOrchestrator initializes with default pool."""
        orchestrator = RuntimeOrchestrator()

        # Should create WarmRuntimePool by default
        self.assertIsNotNone(orchestrator._pool)
        mock_watchdog.set_idle_cleanup.assert_called()

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    def test_acquire_from_pool(self, mock_watchdog):
        """Test acquire returns runtime from pool when available."""
        mock_runtime = MagicMock()
        mock_runtime.config = MagicMock()
        mock_runtime.config.runtime = "docker"

        pooled = PooledRuntime(runtime=mock_runtime, repo_directory="/repo")
        self.mock_pool.acquire.return_value = pooled

        mock_config = MagicMock()
        mock_config.runtime = "docker"
        mock_llm_registry = MagicMock()
        mock_agent = MagicMock()

        result = self.orchestrator.acquire(
            mock_config,
            mock_llm_registry,
            session_id="session-123",
            agent=mock_agent,
            headless_mode=False,
            vcs_provider_tokens=None,
        )

        # Should return pooled runtime
        self.assertEqual(result.runtime, mock_runtime)
        self.assertEqual(result.repo_directory, "/repo")

        # Should record telemetry
        self.mock_telemetry.record_acquire.assert_called_once_with(
            "docker", reused=True
        )

        # Should watch runtime
        mock_watchdog.watch_runtime.assert_called_once()

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    @patch("backend.core.bootstrap.setup.create_runtime")
    def test_acquire_creates_new_runtime(self, mock_create, mock_watchdog):
        """Test acquire creates new runtime when pool is empty."""
        self.mock_pool.acquire.return_value = None

        mock_runtime = MagicMock()
        mock_runtime.config = MagicMock()
        mock_runtime.config.runtime = "local"
        mock_create.return_value = mock_runtime

        mock_config = MagicMock()
        mock_config.runtime = "local"
        mock_llm_registry = MagicMock()
        mock_agent = MagicMock()

        result = self.orchestrator.acquire(
            mock_config,
            mock_llm_registry,
            session_id="session-456",
            agent=mock_agent,
            headless_mode=True,
            vcs_provider_tokens={"github": "token"},
            env_vars={"VAR": "value"},
            user_id="user-123",
        )

        # Should create new runtime
        self.assertEqual(result.runtime, mock_runtime)
        mock_create.assert_called_once()

        # Should record telemetry
        self.mock_telemetry.record_acquire.assert_called_once_with(
            "local", reused=False
        )

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    @patch("backend.core.bootstrap.setup.create_runtime")
    def test_acquire_with_repo_initializer(self, mock_create, mock_watchdog):
        """Test acquire runs repo initializer when provided."""
        self.mock_pool.acquire.return_value = None

        mock_runtime = MagicMock()
        mock_runtime.config = MagicMock()
        mock_runtime.config.runtime = "docker"
        mock_create.return_value = mock_runtime

        mock_repo_init = MagicMock(return_value="/initialized/repo")

        mock_config = MagicMock()
        mock_config.runtime = "docker"
        mock_llm_registry = MagicMock()
        mock_agent = MagicMock()

        result = self.orchestrator.acquire(
            mock_config,
            mock_llm_registry,
            agent=mock_agent,
            headless_mode=False,
            vcs_provider_tokens=None,
            repo_initializer=mock_repo_init,
        )

        # Should call repo initializer
        mock_repo_init.assert_called_once_with(mock_runtime)
        self.assertEqual(result.repo_directory, "/initialized/repo")

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    def test_release(self, mock_watchdog):
        """Test release returns runtime to pool."""
        mock_runtime = MagicMock()
        mock_runtime.config = MagicMock()
        mock_runtime.config.runtime = "docker"

        result = RuntimeAcquireResult(runtime=mock_runtime, repo_directory="/repo")

        self.orchestrator.release(result, key="docker")

        # Should release to pool
        self.mock_pool.release.assert_called_once()

        # Should record telemetry
        self.mock_telemetry.record_release.assert_called_once_with("docker")

        # Should unwatch runtime
        mock_watchdog.unwatch_runtime.assert_called_once_with(mock_runtime)

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    def test_release_infers_key(self, mock_watchdog):
        """Test release infers key from runtime config."""
        mock_runtime = MagicMock()
        mock_runtime.config = MagicMock()
        mock_runtime.config.runtime = "local"

        result = RuntimeAcquireResult(runtime=mock_runtime)

        self.orchestrator.release(result)

        # Should infer key from config
        self.mock_telemetry.record_release.assert_called_once_with("local")

    def test_pool_stats(self):
        """Test pool_stats returns pool statistics."""
        self.mock_pool.stats.return_value = {"docker": 5, "local": 3}

        stats = self.orchestrator.pool_stats()

        self.assertEqual(stats, {"docker": 5, "local": 3})

    def test_idle_reclaim_stats(self):
        """Test idle_reclaim_stats delegates to pool."""
        self.mock_pool.idle_reclaim_stats.return_value = {"docker": 10}

        stats = self.orchestrator.idle_reclaim_stats()

        self.assertEqual(stats, {"docker": 10})

    def test_idle_reclaim_stats_no_method(self):
        """Test idle_reclaim_stats returns empty when method missing."""
        pool_no_method = MagicMock(spec=[])  # No idle_reclaim_stats
        orchestrator = RuntimeOrchestrator(pool=pool_no_method)

        stats = orchestrator.idle_reclaim_stats()

        self.assertEqual(stats, {})

    def test_eviction_stats(self):
        """Test eviction_stats delegates to pool."""
        self.mock_pool.eviction_stats.return_value = {"local": 5}

        stats = self.orchestrator.eviction_stats()

        self.assertEqual(stats, {"local": 5})

    def test_eviction_stats_no_method(self):
        """Test eviction_stats returns empty when method missing."""
        pool_no_method = MagicMock(spec=[])  # No eviction_stats
        orchestrator = RuntimeOrchestrator(pool=pool_no_method)

        stats = orchestrator.eviction_stats()

        self.assertEqual(stats, {})

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    @patch("backend.runtime.orchestrator.IDLE_RECLAIM_SPIKE_THRESHOLD", 5)
    @patch("backend.runtime.orchestrator.logger")
    def test_handle_idle_reclaim_spike(self, mock_logger, mock_watchdog):
        """Test _maybe_record_idle_reclaim_spike detects spikes."""
        self.orchestrator._last_idle_reclaim_totals = {"docker": 0}

        self.orchestrator._maybe_record_idle_reclaim_spike("docker", 10)

        # Should record signal
        self.mock_telemetry.record_scaling_signal.assert_called_once()
        call_args = self.mock_telemetry.record_scaling_signal.call_args[0]
        self.assertIn("overprovision", call_args[0])

        # Should log
        mock_logger.info.assert_called_once()

    @patch("backend.runtime.orchestrator.IDLE_RECLAIM_SPIKE_THRESHOLD", 10)
    def test_handle_idle_reclaim_no_spike(self):
        """Test _maybe_record_idle_reclaim_spike ignores small changes."""
        self.orchestrator._last_idle_reclaim_totals = {"docker": 5}

        self.orchestrator._maybe_record_idle_reclaim_spike("docker", 10)

        # Should not record signal (delta is 5, threshold is 10)
        self.mock_telemetry.record_scaling_signal.assert_not_called()

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    @patch("backend.runtime.orchestrator.EVICTION_SPIKE_THRESHOLD", 3)
    @patch("backend.runtime.orchestrator.logger")
    def test_handle_eviction_spike(self, mock_logger, mock_watchdog):
        """Test _maybe_record_eviction_spike detects spikes."""
        self.orchestrator._last_eviction_totals = {"local": 0}

        self.orchestrator._maybe_record_eviction_spike("local", 5)

        # Should record signal
        self.mock_telemetry.record_scaling_signal.assert_called_once()
        call_args = self.mock_telemetry.record_scaling_signal.call_args[0]
        self.assertIn("capacity_exhausted", call_args[0])

        # Should log warning
        mock_logger.warning.assert_called_once()

    def test_prune_missing_keys(self):
        """Test _prune_missing_keys removes obsolete keys."""
        cache = {"docker": 10, "local": 5, "old_runtime": 3}
        latest_stats = {"docker": 15, "local": 7}

        self.orchestrator._prune_missing_keys(cache, latest_stats)

        # Should remove old_runtime
        self.assertNotIn("old_runtime", cache)
        self.assertIn("docker", cache)
        self.assertIn("local", cache)

    def test_policy_for_key_specific(self):
        """Test _policy_for_key returns key-specific policy."""
        docker_policy = WarmPoolPolicy(max_size=10, ttl_seconds=600.0)
        self.orchestrator._key_pool_policies = {"docker": docker_policy}

        result = self.orchestrator._policy_for_key("docker")

        self.assertEqual(result, docker_policy)

    def test_policy_for_key_default(self):
        """Test _policy_for_key returns default policy."""
        default_policy = WarmPoolPolicy(max_size=5, ttl_seconds=600.0)
        self.orchestrator._default_pool_policy = default_policy
        self.orchestrator._key_pool_policies = {}

        result = self.orchestrator._policy_for_key("unknown")

        self.assertEqual(result, default_policy)

    def test_policy_for_key_none(self):
        """Test _policy_for_key returns None when no policies."""
        self.orchestrator._default_pool_policy = None
        self.orchestrator._key_pool_policies = {}

        result = self.orchestrator._policy_for_key("docker")

        self.assertIsNone(result)

    @patch("backend.runtime.orchestrator.runtime_watchdog")
    @patch("backend.runtime.orchestrator.logger")
    def test_handle_watchdog_saturation(self, mock_logger, mock_watchdog):
        """Test _handle_watchdog_saturation detects saturation."""
        policy = WarmPoolPolicy(max_size=5, ttl_seconds=600.0)
        self.orchestrator._default_pool_policy = policy

        pool_stats = {"docker": 0}  # No idle runtimes
        watched_counts = {"docker": 5}  # All runtimes active

        self.orchestrator._handle_watchdog_saturation(pool_stats, watched_counts)

        # Should detect saturation
        self.assertIn("docker", self.orchestrator._saturated_keys)
        self.mock_telemetry.record_scaling_signal.assert_called_once()
        mock_logger.warning.assert_called_once()

    def test_is_saturated_true(self):
        """Test _is_saturated detects saturation."""
        policy = WarmPoolPolicy(max_size=5, ttl_seconds=600.0)

        result = self.orchestrator._is_saturated(
            policy, "docker", active_count=5, pool_stats={"docker": 0}
        )

        self.assertTrue(result)

    def test_is_saturated_has_idle(self):
        """Test _is_saturated returns False when pool has idle."""
        policy = WarmPoolPolicy(max_size=5, ttl_seconds=600.0)

        result = self.orchestrator._is_saturated(
            policy, "docker", active_count=5, pool_stats={"docker": 2}
        )

        self.assertFalse(result)

    def test_is_saturated_below_max(self):
        """Test _is_saturated returns False when below max."""
        policy = WarmPoolPolicy(max_size=10, ttl_seconds=600.0)

        result = self.orchestrator._is_saturated(
            policy, "docker", active_count=5, pool_stats={"docker": 0}
        )

        self.assertFalse(result)

    def test_is_saturated_no_policy(self):
        """Test _is_saturated returns False when no policy."""
        result = self.orchestrator._is_saturated(
            None, "docker", active_count=100, pool_stats={"docker": 0}
        )

        self.assertFalse(result)

    def test_is_saturated_unlimited_policy(self):
        """Test _is_saturated returns False for unlimited policy."""
        policy = WarmPoolPolicy(max_size=0, ttl_seconds=600.0)  # 0 = unlimited

        result = self.orchestrator._is_saturated(
            policy, "docker", active_count=100, pool_stats={"docker": 0}
        )

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()

