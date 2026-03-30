"""Resource limit enforcement for runtime operations.

Enforces memory, CPU, disk, and other resource limits to prevent resource exhaustion.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psutil

from backend.core.constants import (
    DEFAULT_RUNTIME_MAX_CPU_PERCENT,
    DEFAULT_RUNTIME_MAX_DISK_GB,
    DEFAULT_RUNTIME_MAX_FILE_COUNT,
    DEFAULT_RUNTIME_MAX_MEMORY_MB,
    DEFAULT_RUNTIME_MAX_NETWORK_REQUESTS_PER_MINUTE,
)
from backend.core.errors import ResourceLimitExceededError
from backend.core.logger import app_logger as logger


@dataclass
class ResourceStats:
    """Current resource usage statistics."""

    memory_mb: float
    cpu_percent: float
    disk_gb: float
    file_count: int


@dataclass
class ResourceLimits:
    """Resource limit configuration."""

    max_memory_mb: int = DEFAULT_RUNTIME_MAX_MEMORY_MB
    max_cpu_percent: float = DEFAULT_RUNTIME_MAX_CPU_PERCENT
    max_disk_gb: int = DEFAULT_RUNTIME_MAX_DISK_GB
    max_file_count: int = DEFAULT_RUNTIME_MAX_FILE_COUNT
    max_network_requests_per_minute: int = (
        DEFAULT_RUNTIME_MAX_NETWORK_REQUESTS_PER_MINUTE
    )


class ResourceLimiter:
    """Enforce resource limits on runtime operations.

    This class checks current resource usage against configured limits and
    raises exceptions if limits are exceeded. This prevents resource exhaustion
    attacks and ensures fair resource allocation.
    """

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        workspace_path: str | Path | None = None,
    ) -> None:
        """Initialize resource limiter.

        Args:
            limits: Resource limits configuration. If None, loads from environment.
            workspace_path: Path to workspace for disk/file counting
        """
        if limits is None:
            limits = ResourceLimits(
                max_memory_mb=int(
                    os.getenv(
                        "RUNTIME_MAX_MEMORY_MB", str(DEFAULT_RUNTIME_MAX_MEMORY_MB)
                    )
                ),
                max_cpu_percent=float(
                    os.getenv(
                        "RUNTIME_MAX_CPU_PERCENT", str(DEFAULT_RUNTIME_MAX_CPU_PERCENT)
                    )
                ),
                max_disk_gb=int(
                    os.getenv("RUNTIME_MAX_DISK_GB", str(DEFAULT_RUNTIME_MAX_DISK_GB))
                ),
                max_file_count=int(
                    os.getenv(
                        "RUNTIME_MAX_FILE_COUNT", str(DEFAULT_RUNTIME_MAX_FILE_COUNT)
                    )
                ),
            )

        self.limits = limits
        self.workspace_path = Path(workspace_path) if workspace_path else None

    def get_resource_stats(self) -> ResourceStats:
        """Get current resource usage statistics.

        Returns:
            ResourceStats with current usage
        """
        process = psutil.Process()

        # Memory usage (RSS - Resident Set Size)
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)

        # CPU usage (average over last second)
        cpu_percent = process.cpu_percent(interval=0.1)

        # Disk usage (if workspace path provided)
        disk_gb = 0.0
        file_count = 0
        if self.workspace_path and self.workspace_path.exists():
            try:
                # Get disk usage
                disk_usage = psutil.disk_usage(str(self.workspace_path))
                disk_gb = disk_usage.used / (1024 * 1024 * 1024)

                file_count = sum(
                    len(files) for _, _, files in os.walk(str(self.workspace_path))
                )
            except Exception as e:
                logger.warning("Error calculating disk/file stats: %s", e)

        return ResourceStats(
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            disk_gb=disk_gb,
            file_count=file_count,
        )

    def check_limits(self) -> None:
        """Check current resource usage against limits and raise if exceeded."""
        stats = self.get_resource_stats()

        # Check memory
        if stats.memory_mb > self.limits.max_memory_mb:
            error_msg = f"Memory limit exceeded: {stats.memory_mb:.1f}MB > {self.limits.max_memory_mb}MB"
            logger.warning(error_msg)
            raise ResourceLimitExceededError(error_msg)

        # Check CPU (only warn, don't raise as CPU spikes are common)
        if stats.cpu_percent > self.limits.max_cpu_percent:
            logger.warning(
                "CPU usage high: %.1f%% > %s%%",
                stats.cpu_percent,
                self.limits.max_cpu_percent,
            )

        # Check disk
        if stats.disk_gb > self.limits.max_disk_gb:
            error_msg = f"Disk limit exceeded: {stats.disk_gb:.1f}GB > {self.limits.max_disk_gb}GB"
            logger.warning(error_msg)
            raise ResourceLimitExceededError(error_msg)

        # Check file count
        if stats.file_count > self.limits.max_file_count:
            error_msg = f"File count limit exceeded: {stats.file_count} > {self.limits.max_file_count}"
            logger.warning(error_msg)
            raise ResourceLimitExceededError(error_msg)
