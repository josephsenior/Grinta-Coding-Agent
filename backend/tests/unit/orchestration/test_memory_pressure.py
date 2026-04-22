"""Tests for backend.orchestration.memory_pressure module."""

import os
from unittest.mock import MagicMock, patch

from backend.orchestration.memory_pressure import MemoryPressureMonitor


def _make_monitor(**kwargs) -> MemoryPressureMonitor:
    """Create a monitor with zero baseline for deterministic threshold tests."""
    m = MemoryPressureMonitor(**kwargs)
    m._baseline_rss_mb = 0.0
    return m


class TestMemoryPressureMonitor:
    """Tests for MemoryPressureMonitor class."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        monitor = _make_monitor()
        assert monitor._warn_delta_mb == 768
        assert monitor._crit_delta_mb == 1536
        assert monitor._warn_mb == 768
        assert monitor._crit_mb == 1536
        assert monitor._check_interval == 10.0
        assert monitor._min_history_events == 30
        assert monitor._last_check == 0.0
        assert monitor._last_rss_mb == 0.0
        assert monitor._condensation_count == 0

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        monitor = _make_monitor(warn_mb=512, crit_mb=1024, check_interval_s=5.0)
        assert monitor._warn_mb == 512
        assert monitor._crit_mb == 1024
        assert monitor._check_interval == 5.0

    def test_init_with_environment_variables(self):
        """Test initialization reads environment variables."""
        with patch.dict(
            os.environ,
            {
                'APP_MEM_WARN_MB': '1024',
                'APP_MEM_CRIT_MB': '2048',
                'APP_MEM_CHECK_INTERVAL': '15',
                'APP_MEM_MIN_HISTORY_EVENTS': '12',
            },
        ):
            monitor = _make_monitor()
            assert monitor._warn_mb == 1024
            assert monitor._crit_mb == 2048
            assert monitor._check_interval == 15.0
            assert monitor._min_history_events == 12

    def test_init_custom_overrides_env(self):
        """Test custom values override environment variables."""
        with patch.dict(os.environ, {'APP_MEM_WARN_MB': '1024'}):
            monitor = _make_monitor(warn_mb=512)
            assert monitor._warn_mb == 512

    def test_baseline_aware_thresholds(self):
        """Test that thresholds are relative to the baseline RSS."""
        monitor = MemoryPressureMonitor(warn_mb=768, crit_mb=1536)
        baseline = monitor._baseline_rss_mb
        assert monitor._warn_mb == baseline + 768
        assert monitor._crit_mb == baseline + 1536

    def test_should_condense_false_below_threshold(self):
        """Test should_condense returns False when RSS below threshold."""
        monitor = _make_monitor(warn_mb=1000)
        with patch.object(monitor, '_sample_rss', return_value=500.0):
            assert monitor.should_condense() is False

    def test_should_condense_true_above_threshold(self):
        """Test should_condense returns True when RSS above threshold."""
        monitor = _make_monitor(warn_mb=500)
        with patch.object(monitor, '_sample_rss', return_value=1000.0):
            assert monitor.should_condense() is True

    def test_should_condense_true_at_threshold(self):
        """Test should_condense returns True when RSS at threshold."""
        monitor = _make_monitor(warn_mb=800)
        with patch.object(monitor, '_sample_rss', return_value=800.0):
            assert monitor.should_condense() is True

    def test_should_condense_false_when_rss_none(self):
        """Test should_condense returns False when RSS unavailable."""
        monitor = _make_monitor()
        with patch.object(monitor, '_sample_rss', return_value=None):
            assert monitor.should_condense() is False

    def test_should_condense_false_when_history_is_too_short(self):
        """Short sessions should not trigger proactive condensation."""
        monitor = _make_monitor(warn_mb=500, min_history_events=30)
        with patch.object(monitor, '_sample_rss', return_value=1000.0):
            assert monitor.should_condense(history_events=5) is False

    def test_is_critical_false_below_threshold(self):
        """Test is_critical returns False when RSS below critical."""
        monitor = _make_monitor(crit_mb=2000)
        with patch.object(monitor, '_sample_rss', return_value=1000.0):
            assert monitor.is_critical() is False

    def test_is_critical_true_above_threshold(self):
        """Test is_critical returns True when RSS above critical."""
        monitor = _make_monitor(crit_mb=1000)
        with patch.object(monitor, '_sample_rss', return_value=2000.0):
            assert monitor.is_critical() is True

    def test_is_critical_true_at_threshold(self):
        """Test is_critical returns True when RSS at critical."""
        monitor = _make_monitor(crit_mb=1500)
        with patch.object(monitor, '_sample_rss', return_value=1500.0):
            assert monitor.is_critical() is True

    def test_is_critical_false_when_rss_none(self):
        """Test is_critical returns False when RSS unavailable."""
        monitor = _make_monitor()
        with patch.object(monitor, '_sample_rss', return_value=None):
            assert monitor.is_critical() is False

    def test_record_condensation_increments_count(self):
        """Test record_condensation increments count."""
        monitor = _make_monitor()
        assert monitor._condensation_count == 0
        monitor.record_condensation()
        assert monitor._condensation_count == 1
        monitor.record_condensation()
        assert monitor._condensation_count == 2

    def test_snapshot_returns_diagnostic_info(self):
        """Test snapshot returns diagnostic dictionary."""
        monitor = _make_monitor(warn_mb=512, crit_mb=1024)
        monitor._last_rss_mb = 600.0
        monitor._condensation_count = 3

        snapshot = monitor.snapshot()

        assert snapshot['rss_mb'] == 600.0
        assert snapshot['warn_threshold_mb'] == 512
        assert snapshot['crit_threshold_mb'] == 1024
        assert snapshot['warn_delta_mb'] == 512
        assert snapshot['crit_delta_mb'] == 1024
        assert snapshot['min_history_events'] == 30
        assert snapshot['condensation_count'] == 3
        assert 'psutil_available' in snapshot
        assert 'level' in snapshot
        assert snapshot['baseline_rss_mb'] == 0.0

    def test_snapshot_level_normal(self):
        """Test snapshot level is 'normal' when below thresholds."""
        monitor = _make_monitor(warn_mb=1000, crit_mb=2000)
        monitor._last_rss_mb = 500.0
        assert monitor.snapshot()['level'] == 'normal'

    def test_snapshot_level_warning(self):
        """Test snapshot level is 'warning' when above warn threshold."""
        monitor = _make_monitor(warn_mb=500, crit_mb=2000)
        monitor._last_rss_mb = 1000.0
        assert monitor.snapshot()['level'] == 'warning'

    def test_snapshot_level_critical(self):
        """Test snapshot level is 'critical' when above crit threshold."""
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 2000.0
        assert monitor.snapshot()['level'] == 'critical'

    def test_sample_rss_rate_limited(self):
        """Test _sample_rss caches result within interval."""
        monitor = _make_monitor(check_interval_s=10.0)

        mock_process = MagicMock()
        mock_info = MagicMock()
        mock_info.rss = 1024 * 1024 * 500  # 500 MB
        mock_process.memory_info.return_value = mock_info
        monitor._process = mock_process

        import time

        monitor._last_check = time.monotonic() - 100

        rss1 = monitor._sample_rss()
        assert rss1 == 500.0
        first_call_count = mock_process.memory_info.call_count

        rss2 = monitor._sample_rss()
        assert rss2 == 500.0
        assert mock_process.memory_info.call_count == first_call_count

    def test_sample_rss_samples_after_interval(self):
        """Test _sample_rss samples again after interval expires."""
        monitor = _make_monitor(check_interval_s=0.01)

        mock_process = MagicMock()
        mock_info1 = MagicMock()
        mock_info1.rss = 1024 * 1024 * 500
        mock_info2 = MagicMock()
        mock_info2.rss = 1024 * 1024 * 800
        mock_process.memory_info.side_effect = [mock_info1, mock_info2]
        monitor._process = mock_process

        rss1 = monitor._sample_rss()
        assert rss1 == 500.0

        import time

        time.sleep(0.02)

        rss2 = monitor._sample_rss()
        assert rss2 == 800.0

    def test_sample_rss_returns_none_without_psutil(self):
        """Test _sample_rss returns None when psutil unavailable."""
        monitor = _make_monitor()
        monitor._process = None
        with patch('time.monotonic', return_value=100.0):
            assert monitor._sample_rss() is None

    def test_sample_rss_handles_exception(self):
        """Test _sample_rss handles exceptions gracefully."""
        monitor = _make_monitor()
        mock_process = MagicMock()
        mock_process.memory_info.side_effect = Exception('test error')
        monitor._process = mock_process
        with patch('time.monotonic', return_value=100.0):
            assert monitor._sample_rss() is None

    def test_sample_rss_converts_bytes_to_mb(self):
        """Test _sample_rss correctly converts bytes to MB."""
        monitor = _make_monitor()
        mock_process = MagicMock()
        mock_info = MagicMock()
        mock_info.rss = 1024 * 1024 * 1024  # 1 GB
        mock_process.memory_info.return_value = mock_info
        monitor._process = mock_process
        with patch('time.monotonic', return_value=100.0):
            assert monitor._sample_rss() == 1024.0

    def test_level_str_normal(self):
        """Test _level_str returns 'normal' below warn threshold."""
        monitor = _make_monitor(warn_mb=1000, crit_mb=2000)
        monitor._last_rss_mb = 500.0
        assert monitor._level_str() == 'normal'

    def test_level_str_warning(self):
        """Test _level_str returns 'warning' at/above warn but below crit."""
        monitor = _make_monitor(warn_mb=500, crit_mb=2000)
        monitor._last_rss_mb = 1000.0
        assert monitor._level_str() == 'warning'

    def test_level_str_critical(self):
        """Test _level_str returns 'critical' at/above crit threshold."""
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 1500.0
        assert monitor._level_str() == 'critical'

    def test_level_str_at_warn_boundary(self):
        """Test _level_str returns 'warning' when exactly at warn threshold."""
        monitor = _make_monitor(warn_mb=1000, crit_mb=2000)
        monitor._last_rss_mb = 1000.0
        assert monitor._level_str() == 'warning'

    def test_level_str_at_crit_boundary(self):
        """Test _level_str returns 'critical' when exactly at crit threshold."""
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 1000.0
        assert monitor._level_str() == 'critical'
