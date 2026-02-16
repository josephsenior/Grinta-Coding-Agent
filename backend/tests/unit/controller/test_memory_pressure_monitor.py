"""Tests for backend.controller.memory_pressure.MemoryPressureMonitor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.controller.memory_pressure import MemoryPressureMonitor


# ── __init__ ──────────────────────────────────────────────────────────

class TestMemoryPressureMonitorInit:
    def test_default_thresholds(self):
        m = MemoryPressureMonitor()
        assert m._warn_mb == 768
        assert m._crit_mb == 1536
        assert m._check_interval == 10.0

    def test_custom_thresholds(self):
        m = MemoryPressureMonitor(warn_mb=512, crit_mb=1024, check_interval_s=5.0)
        assert m._warn_mb == 512
        assert m._crit_mb == 1024
        assert m._check_interval == 5.0

    def test_env_var_thresholds(self, monkeypatch):
        monkeypatch.setenv("FORGE_MEM_WARN_MB", "256")
        monkeypatch.setenv("FORGE_MEM_CRIT_MB", "512")
        monkeypatch.setenv("FORGE_MEM_CHECK_INTERVAL", "2")
        m = MemoryPressureMonitor()
        assert m._warn_mb == 256
        assert m._crit_mb == 512
        assert m._check_interval == 2.0


# ── should_condense ───────────────────────────────────────────────────

class TestShouldCondense:
    def test_false_when_below_threshold(self):
        m = MemoryPressureMonitor(warn_mb=1000, check_interval_s=0)
        m._process = MagicMock()
        m._process.memory_info.return_value = MagicMock(rss=500 * 1024 * 1024)
        assert m.should_condense() is False

    def test_true_when_above_warn(self):
        m = MemoryPressureMonitor(warn_mb=400, check_interval_s=0)
        m._process = MagicMock()
        m._process.memory_info.return_value = MagicMock(rss=500 * 1024 * 1024)
        assert m.should_condense() is True

    def test_false_when_no_psutil(self):
        m = MemoryPressureMonitor(check_interval_s=0)
        m._process = None
        assert m.should_condense() is False


# ── is_critical ───────────────────────────────────────────────────────

class TestIsCritical:
    def test_false_below_critical(self):
        m = MemoryPressureMonitor(crit_mb=2000, check_interval_s=0)
        m._process = MagicMock()
        m._process.memory_info.return_value = MagicMock(rss=1000 * 1024 * 1024)
        assert m.is_critical() is False

    def test_true_above_critical(self):
        m = MemoryPressureMonitor(crit_mb=500, check_interval_s=0)
        m._process = MagicMock()
        m._process.memory_info.return_value = MagicMock(rss=600 * 1024 * 1024)
        assert m.is_critical() is True


# ── record_condensation ──────────────────────────────────────────────

class TestRecordCondensation:
    def test_increments_count(self):
        m = MemoryPressureMonitor()
        assert m._condensation_count == 0
        m.record_condensation()
        assert m._condensation_count == 1
        m.record_condensation()
        assert m._condensation_count == 2


# ── snapshot ──────────────────────────────────────────────────────────

class TestSnapshot:
    def test_returns_diagnostic_dict(self):
        m = MemoryPressureMonitor(warn_mb=768, crit_mb=1536)
        snap = m.snapshot()
        assert snap["warn_threshold_mb"] == 768
        assert snap["crit_threshold_mb"] == 1536
        assert snap["condensation_count"] == 0
        assert "level" in snap
        assert "rss_mb" in snap
        assert "psutil_available" in snap

    def test_level_normal(self):
        m = MemoryPressureMonitor(warn_mb=1000, crit_mb=2000)
        m._last_rss_mb = 500
        assert m._level_str() == "normal"

    def test_level_warning(self):
        m = MemoryPressureMonitor(warn_mb=400, crit_mb=2000)
        m._last_rss_mb = 500
        assert m._level_str() == "warning"

    def test_level_critical(self):
        m = MemoryPressureMonitor(warn_mb=400, crit_mb=500)
        m._last_rss_mb = 600
        assert m._level_str() == "critical"


# ── _sample_rss rate-limiting ─────────────────────────────────────────

class TestSampleRss:
    def test_rate_limits_checks(self):
        m = MemoryPressureMonitor(check_interval_s=9999)
        m._process = MagicMock()
        m._process.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)
        m._last_check = 0

        with patch("backend.controller.memory_pressure._HAS_PSUTIL", True):
            # Mock time.monotonic to control rate limiting precisely
            with patch("backend.controller.memory_pressure.time") as mock_time:
                # First call: monotonic returns 100_000, well past _last_check=0
                mock_time.monotonic.return_value = 100_000.0
                result = m._sample_rss()
                assert result is not None
                assert result == pytest.approx(100.0)
                m._process.memory_info.assert_called_once()

                # Second call: monotonic returns 100_001, within 9999s interval
                mock_time.monotonic.return_value = 100_001.0
                result2 = m._sample_rss()
                assert m._process.memory_info.call_count == 1  # Not called again
                assert result2 == pytest.approx(100.0)  # Returns cached value

    def test_handles_memory_info_error(self):
        m = MemoryPressureMonitor(check_interval_s=0)
        m._process = MagicMock()
        m._process.memory_info.side_effect = OSError("no access")
        result = m._sample_rss()
        assert result is None
