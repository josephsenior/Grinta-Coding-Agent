"""Tests for backend.runtime.utils.memory_monitor — MemoryMonitor and LogStream."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.runtime.utils.memory_monitor import LogStream, MemoryMonitor


# ---------------------------------------------------------------------------
# LogStream
# ---------------------------------------------------------------------------

class TestLogStream:
    def test_write_logs_message(self):
        stream = LogStream()
        with patch("backend.runtime.utils.memory_monitor.logger") as mock_log:
            stream.write("Usage: 42 MiB")
            mock_log.info.assert_called_once()

    def test_write_empty_string_ignored(self):
        stream = LogStream()
        with patch("backend.runtime.utils.memory_monitor.logger") as mock_log:
            stream.write("")
            mock_log.info.assert_not_called()

    def test_write_whitespace_ignored(self):
        stream = LogStream()
        with patch("backend.runtime.utils.memory_monitor.logger") as mock_log:
            stream.write("   \n")
            mock_log.info.assert_not_called()

    def test_flush_is_noop(self):
        stream = LogStream()
        stream.flush()  # Should not raise


# ---------------------------------------------------------------------------
# MemoryMonitor
# ---------------------------------------------------------------------------

class TestMemoryMonitor:
    def test_disabled_by_default(self):
        m = MemoryMonitor()
        assert m.enable is False

    def test_start_does_nothing_when_disabled(self):
        m = MemoryMonitor(enable=False)
        m.start_monitoring()
        assert m._monitoring_thread is None

    def test_stop_does_nothing_when_disabled(self):
        m = MemoryMonitor(enable=False)
        m.stop_monitoring()  # should not raise

    def test_start_creates_thread_when_enabled(self):
        m = MemoryMonitor(enable=True)
        with patch("backend.runtime.utils.memory_monitor.memory_usage"):
            m.start_monitoring()
            assert m._monitoring_thread is not None
            # Clean up
            m.stop_monitoring()

    def test_start_idempotent(self):
        m = MemoryMonitor(enable=True)
        with patch("backend.runtime.utils.memory_monitor.memory_usage"):
            m.start_monitoring()
            thread1 = m._monitoring_thread
            m.start_monitoring()
            assert m._monitoring_thread is thread1
            m.stop_monitoring()

    def test_stop_clears_thread(self):
        m = MemoryMonitor(enable=True)
        with patch("backend.runtime.utils.memory_monitor.memory_usage"):
            m.start_monitoring()
            m.stop_monitoring()
            assert m._monitoring_thread is None
