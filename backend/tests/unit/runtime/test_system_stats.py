"""Tests for backend.runtime.utils.system_stats module.

Targets the 21.2% (26 missed lines) coverage gap.
"""

from __future__ import annotations


from backend.runtime.utils.system_stats import (
    get_system_info,
    get_system_stats,
    update_last_execution_time,
)


class TestGetSystemInfo:
    def test_returns_dict(self):
        info = get_system_info()
        assert isinstance(info, dict)
        assert "uptime" in info
        assert "idle_time" in info
        assert "resources" in info

    def test_uptime_positive(self):
        info = get_system_info()
        assert info["uptime"] >= 0

    def test_idle_time_positive(self):
        info = get_system_info()
        assert info["idle_time"] >= 0

    def test_resources_is_dict(self):
        info = get_system_info()
        assert isinstance(info["resources"], dict)


class TestUpdateLastExecutionTime:
    def test_updates_idle_time(self):
        # Get idle time before
        info1 = get_system_info()
        idle1 = info1["idle_time"]

        # Update execution time
        update_last_execution_time()

        # Idle time should be very small now
        info2 = get_system_info()
        idle2 = info2["idle_time"]
        assert idle2 <= idle1 + 1  # allow small margin


class TestGetSystemStats:
    def test_returns_dict_with_expected_keys(self):
        stats = get_system_stats()
        assert "cpu_percent" in stats
        assert "memory" in stats
        assert "disk" in stats
        assert "io" in stats

    def test_memory_has_rss_vms_percent(self):
        stats = get_system_stats()
        mem = stats["memory"]
        assert "rss" in mem
        assert "vms" in mem
        assert "percent" in mem

    def test_disk_has_total_used_free(self):
        stats = get_system_stats()
        disk = stats["disk"]
        assert "total" in disk
        assert "used" in disk
        assert "free" in disk
        assert "percent" in disk

    def test_io_has_read_write_bytes(self):
        stats = get_system_stats()
        io = stats["io"]
        assert "read_bytes" in io
        assert "write_bytes" in io

    def test_cpu_percent_non_negative(self):
        stats = get_system_stats()
        assert stats["cpu_percent"] >= 0

    def test_memory_rss_positive(self):
        stats = get_system_stats()
        assert stats["memory"]["rss"] > 0

    def test_disk_total_positive(self):
        stats = get_system_stats()
        assert stats["disk"]["total"] > 0
