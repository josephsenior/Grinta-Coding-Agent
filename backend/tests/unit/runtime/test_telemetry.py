"""Unit tests for backend.runtime.telemetry."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from backend.runtime.telemetry import RuntimeTelemetry


class TestRuntimeTelemetry(TestCase):
    """Test RuntimeTelemetry class."""

    def setUp(self):
        """Set up test fixtures."""
        self.telemetry = RuntimeTelemetry()

    def tearDown(self):
        """Clean up after each test."""
        self.telemetry.reset()

    def test_initialization(self):
        """Test RuntimeTelemetry initialization."""
        telemetry = RuntimeTelemetry()
        snapshot = telemetry.snapshot()

        self.assertEqual(snapshot["acquire"], {})
        self.assertEqual(snapshot["reuse"], {})
        self.assertEqual(snapshot["release"], {})
        self.assertEqual(snapshot["watchdog"], {})
        self.assertEqual(snapshot["scaling"], {})

    def test_record_acquire_new(self):
        """Test recording acquisition without reuse."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_acquire("key1", reused=False)

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["acquire"]["key1"], 1)
        self.assertEqual(snapshot["reuse"], {})
        mock_logger.debug.assert_called_once()

    def test_record_acquire_reused(self):
        """Test recording acquisition with reuse."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_acquire("key1", reused=True)

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["acquire"]["key1"], 1)
        self.assertEqual(snapshot["reuse"]["key1"], 1)
        mock_logger.debug.assert_called_once()

    def test_record_acquire_multiple_keys(self):
        """Test recording acquisitions for multiple keys."""
        self.telemetry.record_acquire("key1", reused=False)
        self.telemetry.record_acquire("key2", reused=True)
        self.telemetry.record_acquire("key1", reused=True)

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["acquire"]["key1"], 2)
        self.assertEqual(snapshot["acquire"]["key2"], 1)
        self.assertEqual(snapshot["reuse"]["key1"], 1)
        self.assertEqual(snapshot["reuse"]["key2"], 1)

    def test_record_acquire_increments_counter(self):
        """Test that record_acquire increments existing counters."""
        self.telemetry.record_acquire("key1", reused=False)
        self.telemetry.record_acquire("key1", reused=False)
        self.telemetry.record_acquire("key1", reused=True)

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["acquire"]["key1"], 3)
        self.assertEqual(snapshot["reuse"]["key1"], 1)

    def test_record_release(self):
        """Test recording runtime release."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_release("key1")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["release"]["key1"], 1)
        mock_logger.debug.assert_called_once()

    def test_record_release_multiple(self):
        """Test recording multiple releases."""
        self.telemetry.record_release("key1")
        self.telemetry.record_release("key2")
        self.telemetry.record_release("key1")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["release"]["key1"], 2)
        self.assertEqual(snapshot["release"]["key2"], 1)

    def test_record_watchdog_termination(self):
        """Test recording watchdog termination."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_watchdog_termination("key1", "idle")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["watchdog"]["key1|idle"], 1)
        mock_logger.warning.assert_called_once()
        self.assertIn("watchdog terminated", mock_logger.warning.call_args[0][0])

    def test_record_watchdog_termination_multiple_reasons(self):
        """Test recording watchdog terminations with different reasons."""
        self.telemetry.record_watchdog_termination("key1", "idle")
        self.telemetry.record_watchdog_termination("key1", "eviction")
        self.telemetry.record_watchdog_termination("key2", "idle")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["watchdog"]["key1|idle"], 1)
        self.assertEqual(snapshot["watchdog"]["key1|eviction"], 1)
        self.assertEqual(snapshot["watchdog"]["key2|idle"], 1)

    def test_record_watchdog_termination_increments(self):
        """Test that watchdog termination increments counters."""
        self.telemetry.record_watchdog_termination("key1", "idle")
        self.telemetry.record_watchdog_termination("key1", "idle")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["watchdog"]["key1|idle"], 2)

    def test_record_scaling_signal_info(self):
        """Test recording scaling signal with info severity."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_scaling_signal("pool_growth", severity="info")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["scaling"]["pool_growth"], 1)
        mock_logger.info.assert_called_once()
        self.assertIn("scaling signal", mock_logger.info.call_args[0][0])

    def test_record_scaling_signal_warning(self):
        """Test recording scaling signal with warning severity."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_scaling_signal("saturation", severity="warning")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["scaling"]["saturation"], 1)
        mock_logger.warning.assert_called_once()
        self.assertIn("scaling signal", mock_logger.warning.call_args[0][0])

    def test_record_scaling_signal_default_severity(self):
        """Test recording scaling signal with default severity (info)."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_scaling_signal("default_signal")

        mock_logger.info.assert_called_once()

    def test_record_scaling_signal_multiple(self):
        """Test recording multiple scaling signals."""
        self.telemetry.record_scaling_signal("signal1")
        self.telemetry.record_scaling_signal("signal2")
        self.telemetry.record_scaling_signal("signal1")

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["scaling"]["signal1"], 2)
        self.assertEqual(snapshot["scaling"]["signal2"], 1)

    def test_snapshot_structure(self):
        """Test snapshot returns correct structure."""
        self.telemetry.record_acquire("key1", reused=False)
        self.telemetry.record_release("key1")
        self.telemetry.record_watchdog_termination("key1", "idle")
        self.telemetry.record_scaling_signal("signal1")

        snapshot = self.telemetry.snapshot()

        self.assertIn("acquire", snapshot)
        self.assertIn("reuse", snapshot)
        self.assertIn("release", snapshot)
        self.assertIn("watchdog", snapshot)
        self.assertIn("scaling", snapshot)
        self.assertIsInstance(snapshot["acquire"], dict)
        self.assertIsInstance(snapshot["reuse"], dict)
        self.assertIsInstance(snapshot["release"], dict)
        self.assertIsInstance(snapshot["watchdog"], dict)
        self.assertIsInstance(snapshot["scaling"], dict)

    def test_snapshot_watchdog_key_format(self):
        """Test that watchdog keys are formatted as 'key|reason'."""
        self.telemetry.record_watchdog_termination("runtime1", "idle")
        self.telemetry.record_watchdog_termination("runtime2", "eviction")

        snapshot = self.telemetry.snapshot()

        self.assertIn("runtime1|idle", snapshot["watchdog"])
        self.assertIn("runtime2|eviction", snapshot["watchdog"])

    def test_reset(self):
        """Test reset clears all counters."""
        self.telemetry.record_acquire("key1", reused=True)
        self.telemetry.record_release("key1")
        self.telemetry.record_watchdog_termination("key1", "idle")
        self.telemetry.record_scaling_signal("signal1")

        self.telemetry.reset()
        snapshot = self.telemetry.snapshot()

        self.assertEqual(snapshot["acquire"], {})
        self.assertEqual(snapshot["reuse"], {})
        self.assertEqual(snapshot["release"], {})
        self.assertEqual(snapshot["watchdog"], {})
        self.assertEqual(snapshot["scaling"], {})

    def test_reset_multiple_times(self):
        """Test that reset can be called multiple times."""
        self.telemetry.record_acquire("key1", reused=False)
        self.telemetry.reset()
        self.telemetry.record_acquire("key2", reused=False)
        self.telemetry.reset()

        snapshot = self.telemetry.snapshot()
        self.assertEqual(snapshot["acquire"], {})

    def test_comprehensive_workflow(self):
        """Test a comprehensive workflow with all operations."""
        # Acquire some runtimes
        self.telemetry.record_acquire("runtime1", reused=False)
        self.telemetry.record_acquire("runtime2", reused=True)
        self.telemetry.record_acquire("runtime1", reused=True)

        # Release some runtimes
        self.telemetry.record_release("runtime1")
        self.telemetry.record_release("runtime2")

        # Record watchdog terminations
        self.telemetry.record_watchdog_termination("runtime1", "idle")
        self.telemetry.record_watchdog_termination("runtime3", "eviction")

        # Record scaling signals
        self.telemetry.record_scaling_signal("pool_growth", severity="info")
        self.telemetry.record_scaling_signal("saturation_detected", severity="warning")

        snapshot = self.telemetry.snapshot()

        # Verify acquire counts
        self.assertEqual(snapshot["acquire"]["runtime1"], 2)
        self.assertEqual(snapshot["acquire"]["runtime2"], 1)

        # Verify reuse counts
        self.assertEqual(snapshot["reuse"]["runtime1"], 1)
        self.assertEqual(snapshot["reuse"]["runtime2"], 1)

        # Verify release counts
        self.assertEqual(snapshot["release"]["runtime1"], 1)
        self.assertEqual(snapshot["release"]["runtime2"], 1)

        # Verify watchdog counts
        self.assertEqual(snapshot["watchdog"]["runtime1|idle"], 1)
        self.assertEqual(snapshot["watchdog"]["runtime3|eviction"], 1)

        # Verify scaling signal counts
        self.assertEqual(snapshot["scaling"]["pool_growth"], 1)
        self.assertEqual(snapshot["scaling"]["saturation_detected"], 1)

    def test_global_runtime_telemetry_singleton(self):
        """Test that global runtime_telemetry is created."""
        from backend.runtime.telemetry import runtime_telemetry

        self.assertIsInstance(runtime_telemetry, RuntimeTelemetry)

    def test_record_acquire_logging_content(self):
        """Test that record_acquire logs contain expected information."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_acquire("test-key", reused=True)

        call_args = mock_logger.debug.call_args[0]
        self.assertIn("acquire", call_args[0])
        self.assertIn("key=%s", call_args[0])
        self.assertIn("reused=%s", call_args[0])
        self.assertEqual(call_args[1], "test-key")
        self.assertEqual(call_args[2], True)

    def test_record_release_logging_content(self):
        """Test that record_release logs contain expected information."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_release("test-key")

        call_args = mock_logger.debug.call_args[0]
        self.assertIn("release", call_args[0])
        self.assertIn("key=%s", call_args[0])
        self.assertEqual(call_args[1], "test-key")

    def test_record_watchdog_termination_logging_content(self):
        """Test that record_watchdog_termination logs contain expected information."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_watchdog_termination("test-key", "test-reason")

        call_args = mock_logger.warning.call_args[0]
        self.assertIn("watchdog terminated", call_args[0])
        self.assertIn("key=%s", call_args[0])
        self.assertIn("reason=%s", call_args[0])
        self.assertEqual(call_args[1], "test-key")
        self.assertEqual(call_args[2], "test-reason")

    def test_record_scaling_signal_logging_content(self):
        """Test that record_scaling_signal logs contain expected information."""
        with patch("backend.runtime.telemetry.logger") as mock_logger:
            self.telemetry.record_scaling_signal("test-signal", severity="warning")

        call_args = mock_logger.warning.call_args[0]
        self.assertIn("scaling signal", call_args[0])
        self.assertIn("signal=%s", call_args[0])
        self.assertIn("severity=%s", call_args[0])
        self.assertEqual(call_args[1], "test-signal")
        self.assertEqual(call_args[2], "warning")

    def test_empty_snapshot_dict_values(self):
        """Test that empty snapshot returns dict instances."""
        snapshot = self.telemetry.snapshot()

        # All should be dict instances, not Counter instances
        self.assertEqual(type(snapshot["acquire"]), dict)
        self.assertEqual(type(snapshot["reuse"]), dict)
        self.assertEqual(type(snapshot["release"]), dict)
        self.assertEqual(type(snapshot["watchdog"]), dict)
        self.assertEqual(type(snapshot["scaling"]), dict)

    def test_snapshot_does_not_modify_internal_state(self):
        """Test that taking a snapshot doesn't affect internal counters."""
        self.telemetry.record_acquire("key1", reused=False)

        snapshot1 = self.telemetry.snapshot()
        snapshot2 = self.telemetry.snapshot()

        self.assertEqual(snapshot1["acquire"]["key1"], 1)
        self.assertEqual(snapshot2["acquire"]["key1"], 1)

    def test_counters_are_independent(self):
        """Test that different counter types are independent."""
        self.telemetry.record_acquire("key1", reused=False)
        self.telemetry.record_release("key1")
        self.telemetry.record_watchdog_termination("key1", "idle")

        snapshot = self.telemetry.snapshot()

        # All three operations should be counted independently
        self.assertEqual(snapshot["acquire"]["key1"], 1)
        self.assertEqual(snapshot["release"]["key1"], 1)
        self.assertEqual(snapshot["watchdog"]["key1|idle"], 1)

    def test_special_characters_in_keys(self):
        """Test handling of special characters in keys."""
        self.telemetry.record_acquire("key-with-dash", reused=False)
        self.telemetry.record_acquire("key.with.dot", reused=False)
        self.telemetry.record_acquire("key_with_underscore", reused=False)

        snapshot = self.telemetry.snapshot()

        self.assertEqual(snapshot["acquire"]["key-with-dash"], 1)
        self.assertEqual(snapshot["acquire"]["key.with.dot"], 1)
        self.assertEqual(snapshot["acquire"]["key_with_underscore"], 1)

    def test_special_characters_in_watchdog_reason(self):
        """Test handling of special characters in watchdog reason."""
        self.telemetry.record_watchdog_termination("key1", "reason-with-dash")
        self.telemetry.record_watchdog_termination("key1", "reason.with.dot")

        snapshot = self.telemetry.snapshot()

        self.assertEqual(snapshot["watchdog"]["key1|reason-with-dash"], 1)
        self.assertEqual(snapshot["watchdog"]["key1|reason.with.dot"], 1)
