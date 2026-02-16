"""Unit tests for backend.controller.memory_pressure — Memory pressure monitoring."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from backend.controller.memory_pressure import MemoryPressureMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monitor(warn_mb=768, crit_mb=1536, check_interval_s=0.0):
    """Create a monitor with instant check interval for testing."""
    return MemoryPressureMonitor(
        warn_mb=warn_mb,
        crit_mb=crit_mb,
        check_interval_s=check_interval_s,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self):
        monitor = MemoryPressureMonitor()
        assert monitor._warn_mb == 768
        assert monitor._crit_mb == 1536
        assert monitor._condensation_count == 0

    def test_custom_thresholds(self):
        monitor = _make_monitor(warn_mb=256, crit_mb=512)
        assert monitor._warn_mb == 256
        assert monitor._crit_mb == 512


# ---------------------------------------------------------------------------
# should_condense
# ---------------------------------------------------------------------------


class TestShouldCondense:
    def test_returns_false_when_below_threshold(self):
        monitor = _make_monitor(warn_mb=1000)
        # Mock the RSS sampling to return low value
        monitor._sample_rss = lambda: 500.0
        assert monitor.should_condense() is False

    def test_returns_true_when_above_warning(self):
        monitor = _make_monitor(warn_mb=500)
        monitor._sample_rss = lambda: 600.0
        assert monitor.should_condense() is True

    def test_returns_true_at_exact_threshold(self):
        monitor = _make_monitor(warn_mb=500)
        monitor._sample_rss = lambda: 500.0
        assert monitor.should_condense() is True

    def test_returns_false_when_rss_unavailable(self):
        monitor = _make_monitor()
        monitor._sample_rss = lambda: None
        assert monitor.should_condense() is False


# ---------------------------------------------------------------------------
# is_critical
# ---------------------------------------------------------------------------


class TestIsCritical:
    def test_false_below_critical(self):
        monitor = _make_monitor(crit_mb=1000)
        monitor._sample_rss = lambda: 800.0
        assert monitor.is_critical() is False

    def test_true_above_critical(self):
        monitor = _make_monitor(crit_mb=1000)
        monitor._sample_rss = lambda: 1200.0
        assert monitor.is_critical() is True

    def test_true_at_exact_critical(self):
        monitor = _make_monitor(crit_mb=1000)
        monitor._sample_rss = lambda: 1000.0
        assert monitor.is_critical() is True

    def test_false_when_rss_unavailable(self):
        monitor = _make_monitor()
        monitor._sample_rss = lambda: None
        assert monitor.is_critical() is False


# ---------------------------------------------------------------------------
# record_condensation
# ---------------------------------------------------------------------------


class TestRecordCondensation:
    def test_increments_count(self):
        monitor = _make_monitor()
        assert monitor._condensation_count == 0
        monitor.record_condensation()
        assert monitor._condensation_count == 1
        monitor.record_condensation()
        assert monitor._condensation_count == 2


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_fields(self):
        monitor = _make_monitor(warn_mb=256, crit_mb=512)
        snap = monitor.snapshot()
        assert snap["warn_threshold_mb"] == 256
        assert snap["crit_threshold_mb"] == 512
        assert snap["condensation_count"] == 0
        assert "rss_mb" in snap
        assert "psutil_available" in snap
        assert "level" in snap

    def test_snapshot_after_condensation(self):
        monitor = _make_monitor()
        monitor.record_condensation()
        monitor.record_condensation()
        snap = monitor.snapshot()
        assert snap["condensation_count"] == 2


# ---------------------------------------------------------------------------
# _level_str
# ---------------------------------------------------------------------------


class TestLevelStr:
    def test_normal_level(self):
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 200.0
        assert monitor._level_str() == "normal"

    def test_warning_level(self):
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 600.0
        assert monitor._level_str() == "warning"

    def test_critical_level(self):
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 1200.0
        assert monitor._level_str() == "critical"

    def test_at_exact_warning(self):
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 500.0
        assert monitor._level_str() == "warning"

    def test_at_exact_critical(self):
        monitor = _make_monitor(warn_mb=500, crit_mb=1000)
        monitor._last_rss_mb = 1000.0
        assert monitor._level_str() == "critical"


# ---------------------------------------------------------------------------
# _sample_rss rate limiting
# ---------------------------------------------------------------------------


class TestRSSRateLimiting:
    def test_rate_limits_calls(self):
        monitor = _make_monitor(check_interval_s=100.0)
        # First call outside interval
        monitor._last_check = 0.0
        if monitor._process is not None:
            result1 = monitor._sample_rss()
            # Second call within interval should use cached
            monitor._last_check = time.monotonic()  # fresh timestamp
            result2 = monitor._sample_rss()
            # Second call should return cached _last_rss_mb
            assert result2 == monitor._last_rss_mb

    def test_no_psutil_returns_none(self):
        monitor = _make_monitor(check_interval_s=0.0)
        monitor._process = None  # simulate no psutil
        monitor._last_check = 0.0
        assert monitor._sample_rss() is None
