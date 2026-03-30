"""Memory pressure monitor with proactive condensation trigger.

Monitors the backend process RSS and triggers condensation before the
process hits hard memory limits.  Integrates as a circuit breaker that
the controller checks each iteration.

Usage::

    pressure = MemoryPressureMonitor(threshold_mb=1024)
    if pressure.should_condense():
        # trigger condensation
        ...
"""

from __future__ import annotations

import os
import time
from typing import Any

from backend.core.logger import app_logger as logger

# Optional psutil — degrade gracefully on platforms where it is unavailable.
try:
    import psutil  # type: ignore[import-untyped]

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class MemoryPressureMonitor:
    """Monitors process RSS and signals when condensation should happen.

    Thresholds are configurable via environment variables:
    - ``APP_MEM_WARN_MB``  — warning threshold (default 768 MB)
    - ``APP_MEM_CRIT_MB``  — critical threshold (default 1536 MB)
    - ``APP_MEM_CHECK_INTERVAL`` — minimum seconds between checks (default 10)

    The monitor exposes three levels:

    * **normal** — RSS below warning threshold
    * **warning** — RSS ≥ warning but < critical threshold → suggest condensation
    * **critical** — RSS ≥ critical threshold → force condensation
    """

    def __init__(
        self,
        warn_mb: int | None = None,
        crit_mb: int | None = None,
        check_interval_s: float | None = None,
    ) -> None:
        self._warn_mb = warn_mb or int(os.getenv("APP_MEM_WARN_MB", "768"))
        self._crit_mb = crit_mb or int(os.getenv("APP_MEM_CRIT_MB", "1536"))
        self._check_interval = check_interval_s or float(
            os.getenv("APP_MEM_CHECK_INTERVAL", "10")
        )
        self._last_check: float = 0.0
        self._last_rss_mb: float = 0.0
        self._condensation_count: int = 0
        self._process: Any = None
        if _HAS_PSUTIL:
            self._process = psutil.Process(os.getpid())

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def should_condense(self) -> bool:
        """Return True if memory pressure warrants proactive condensation."""
        rss = self._sample_rss()
        if rss is None:
            return False
        return rss >= self._warn_mb

    def is_critical(self) -> bool:
        """Return True if memory is at a critical level."""
        rss = self._sample_rss()
        if rss is None:
            return False
        return rss >= self._crit_mb

    def record_condensation(self) -> None:
        """Call after a condensation pass completes."""
        self._condensation_count += 1

    def snapshot(self) -> dict[str, Any]:
        """Return diagnostic snapshot for debug endpoints."""
        return {
            "rss_mb": self._last_rss_mb,
            "warn_threshold_mb": self._warn_mb,
            "crit_threshold_mb": self._crit_mb,
            "condensation_count": self._condensation_count,
            "psutil_available": _HAS_PSUTIL,
            "level": self._level_str(),
        }

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _sample_rss(self) -> float | None:
        """Read process RSS, rate-limited to avoid overhead."""
        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return self._last_rss_mb if self._last_rss_mb > 0 else None

        self._last_check = now

        if not _HAS_PSUTIL or self._process is None:
            return None

        try:
            info = self._process.memory_info()
            self._last_rss_mb = info.rss / (1024 * 1024)
            return self._last_rss_mb
        except Exception:
            logger.debug("Failed to read RSS", exc_info=True)
            return None

    def _level_str(self) -> str:
        if self._last_rss_mb >= self._crit_mb:
            return "critical"
        if self._last_rss_mb >= self._warn_mb:
            return "warning"
        return "normal"
