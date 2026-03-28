"""Tests for backend.execution.utils.resource_limits — ResourceLimiter."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.errors import ResourceLimitExceededError
from backend.execution.utils.resource_limits import (
    ResourceLimiter,
    ResourceLimits,
    ResourceStats,
)


# ===================================================================
# Dataclasses
# ===================================================================


class TestResourceStats:
    def test_construction(self):
        s = ResourceStats(
            memory_mb=512.0, cpu_percent=25.0, disk_gb=10.0, file_count=100
        )
        assert s.memory_mb == 512.0
        assert s.cpu_percent == 25.0
        assert s.disk_gb == 10.0
        assert s.file_count == 100


class TestResourceLimits:
    def test_defaults(self):
        limits = ResourceLimits()
        assert limits.max_memory_mb > 0
        assert limits.max_cpu_percent > 0

    def test_custom(self):
        limits = ResourceLimits(
            max_memory_mb=256, max_cpu_percent=50.0, max_disk_gb=5, max_file_count=1000
        )
        assert limits.max_memory_mb == 256


# ===================================================================
# ResourceLimiter
# ===================================================================


class TestResourceLimiter:
    def test_init_with_defaults(self):
        limiter = ResourceLimiter()
        assert limiter.limits is not None
        assert limiter.workspace_path is None

    def test_init_with_custom_limits(self, tmp_path):
        limits = ResourceLimits(max_memory_mb=128)
        limiter = ResourceLimiter(limits=limits, workspace_path=str(tmp_path))
        assert limiter.limits.max_memory_mb == 128
        assert limiter.workspace_path is not None


class TestCheckLimits:
    def _mock_stats(self, memory_mb=100, cpu_percent=10, disk_gb=1, file_count=10):
        return ResourceStats(
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            disk_gb=disk_gb,
            file_count=file_count,
        )

    def test_under_limits_passes(self):
        limits = ResourceLimits(
            max_memory_mb=1024,
            max_cpu_percent=100,
            max_disk_gb=100,
            max_file_count=10000,
        )
        limiter = ResourceLimiter(limits=limits)
        with patch.object(
            limiter, "get_resource_stats", return_value=self._mock_stats()
        ):
            limiter.check_limits()  # Should not raise

    def test_memory_exceeded_raises(self):
        limits = ResourceLimits(
            max_memory_mb=50, max_cpu_percent=100, max_disk_gb=100, max_file_count=10000
        )
        limiter = ResourceLimiter(limits=limits)
        with patch.object(
            limiter, "get_resource_stats", return_value=self._mock_stats(memory_mb=200)
        ):
            with pytest.raises(ResourceLimitExceededError, match="Memory limit"):
                limiter.check_limits()

    def test_disk_exceeded_raises(self):
        limits = ResourceLimits(
            max_memory_mb=1024, max_cpu_percent=100, max_disk_gb=1, max_file_count=10000
        )
        limiter = ResourceLimiter(limits=limits)
        with patch.object(
            limiter, "get_resource_stats", return_value=self._mock_stats(disk_gb=5)
        ):
            with pytest.raises(ResourceLimitExceededError, match="Disk limit"):
                limiter.check_limits()

    def test_file_count_exceeded_raises(self):
        limits = ResourceLimits(
            max_memory_mb=1024, max_cpu_percent=100, max_disk_gb=100, max_file_count=5
        )
        limiter = ResourceLimiter(limits=limits)
        with patch.object(
            limiter, "get_resource_stats", return_value=self._mock_stats(file_count=50)
        ):
            with pytest.raises(ResourceLimitExceededError, match="File count"):
                limiter.check_limits()

    def test_cpu_exceeded_only_warns(self):
        """CPU exceeds limit but only warns, doesn't raise."""
        limits = ResourceLimits(
            max_memory_mb=1024,
            max_cpu_percent=10,
            max_disk_gb=100,
            max_file_count=10000,
        )
        limiter = ResourceLimiter(limits=limits)
        with patch.object(
            limiter, "get_resource_stats", return_value=self._mock_stats(cpu_percent=99)
        ):
            limiter.check_limits()  # Should not raise
