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

import asyncio
import os
import statistics
import time
from collections import deque
from typing import Any, Awaitable, Callable

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
        - ``APP_MEM_CONDENSE_COOLDOWN_S`` — warning-level cooldown after a
            sync condensation pass (default 30)
        - ``APP_MEM_PREWARM_COOLDOWN_S`` — separate cooldown after a
            successful background pre-warm (default 5). Pre-warm cooldowns
            must NOT block emergency sync condensation, so the two clocks
            are tracked independently (Phase 3.14, "bifurcate cooldown").

    The monitor exposes three levels:

    * **normal** — RSS below warning threshold
    * **warning** — RSS ≥ warning but < critical threshold → suggest condensation
    * **critical** — RSS ≥ critical threshold → force condensation

    Background pre-warm (Phase 3.11)
    ---------------------------------
    Callers may speculatively start a background condensation task while
    still at WARNING level via :meth:`start_prewarm`. The result is held
    in :attr:`_prewarmed_value` until consumed by :meth:`consume_prewarmed`
    on the next agent turn boundary (Phase 3.12 hot-swap path). A failed
    pre-warm never blocks subsequent attempts and does not count toward
    the critical-sync cooldown.
    """

    def __init__(
        self,
        warn_mb: int | None = None,
        crit_mb: int | None = None,
        check_interval_s: float | None = None,
        cooldown_s: float | None = None,
        min_history_events: int | None = None,
        prewarm_cooldown_s: float | None = None,
    ) -> None:
        self._warn_delta_mb = warn_mb or int(os.getenv('APP_MEM_WARN_MB', '768'))
        self._crit_delta_mb = crit_mb or int(os.getenv('APP_MEM_CRIT_MB', '1536'))
        self._check_interval = (
            check_interval_s
            if check_interval_s is not None
            else float(os.getenv('APP_MEM_CHECK_INTERVAL', '10'))
        )
        self._cooldown_s = (
            cooldown_s
            if cooldown_s is not None
            else float(os.getenv('APP_MEM_CONDENSE_COOLDOWN_S', '30'))
        )
        self._prewarm_cooldown_s = (
            prewarm_cooldown_s
            if prewarm_cooldown_s is not None
            else float(os.getenv('APP_MEM_PREWARM_COOLDOWN_S', '5'))
        )
        self._min_history_events = (
            min_history_events
            if min_history_events is not None
            else int(os.getenv('APP_MEM_MIN_HISTORY_EVENTS', '30'))
        )
        self._prewarm_ratio = float(os.getenv('APP_MEM_PREWARM_RATIO', '0.5'))
        self._signal_ratio = float(os.getenv('APP_MEM_SIGNAL_RATIO', '0.75'))
        self._last_check: float = 0.0
        self._last_rss_mb: float = 0.0
        self._condensation_count: int = 0
        # Bifurcated cooldowns (Phase 3.14): sync condensation is the
        # blocking event the agent must wait on; pre-warm is opportunistic.
        self._last_condensation_at: float = 0.0
        self._last_prewarm_at: float = 0.0
        # Rolling P50 of past condensation durations (Phase 3.13). Bounded
        # deque so the estimator naturally adapts to model/workload drift.
        self._condense_durations: deque[float] = deque(maxlen=20)
        # Background pre-warm slot (Phase 3.11).
        self._prewarm_task: asyncio.Task[Any] | None = None
        self._prewarmed_value: Any = None
        self._process: Any = None
        self._baseline_rss_mb: float = 0.0
        if _HAS_PSUTIL:
            self._process = psutil.Process(os.getpid())
            try:
                info = self._process.memory_info()
                self._baseline_rss_mb = info.rss / (1024 * 1024)
            except Exception:
                self._baseline_rss_mb = 0.0

    @property
    def _warn_mb(self) -> float:
        """Effective warning threshold: baseline + configured delta."""
        return self._baseline_rss_mb + self._warn_delta_mb

    @property
    def _crit_mb(self) -> float:
        """Effective critical threshold: baseline + configured delta."""
        return self._baseline_rss_mb + self._crit_delta_mb

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def should_prewarm(self, history_events: int | None = None) -> bool:
        """Return True when background compaction pre-warm should start."""
        if history_events is not None and history_events < self._min_history_events:
            return False
        if self.pressure_ratio() >= self._prewarm_ratio:
            return True
        return self.should_condense(history_events=history_events)

    def should_signal_pressure(self) -> bool:
        """Return True when the orchestrator should schedule foreground compaction."""
        if self.is_critical():
            return True
        if self.pressure_ratio() < self._signal_ratio:
            return False
        if self._last_condensation_at > 0:
            elapsed = time.monotonic() - self._last_condensation_at
            if elapsed < self._cooldown_s:
                return False
        return True

    def should_condense(self, history_events: int | None = None) -> bool:
        """Return True if memory pressure warrants proactive condensation.

        When ``history_events`` is provided, very short sessions are ignored
        because condensation cannot reduce history meaningfully yet.
        """
        rss = self._sample_rss()
        if rss is None:
            return False
        if history_events is not None and history_events < self._min_history_events:
            return False
        if rss >= self._crit_mb:
            return True
        if rss < self._warn_mb:
            return False
        if self._last_condensation_at > 0:
            elapsed = time.monotonic() - self._last_condensation_at
            if elapsed < self._cooldown_s:
                return False
        return True

    def is_critical(self) -> bool:
        """Return True if memory is at a critical level."""
        rss = self._sample_rss()
        if rss is None:
            return False
        return rss >= self._crit_mb

    def record_condensation(self, duration_s: float | None = None) -> None:
        """Call after a *synchronous* condensation pass completes.

        ``duration_s`` is optionally fed to the rolling P50 estimator
        (Phase 3.13) so the next call to :meth:`eta_seconds` can give the
        UI / agent a realistic ETA based on observed compaction cost.
        """
        self._condensation_count += 1
        self._last_condensation_at = time.monotonic()
        if duration_s is not None and duration_s >= 0:
            self._condense_durations.append(float(duration_s))

    # ------------------------------------------------------------------ #
    # Phase 3.11 — background pre-warm
    # ------------------------------------------------------------------ #

    @property
    def is_prewarming(self) -> bool:
        """Return True when a background pre-warm task is in flight."""
        return self._prewarm_task is not None and not self._prewarm_task.done()

    @property
    def has_prewarmed(self) -> bool:
        """Return True when a completed pre-warm result is waiting to be consumed."""
        return self._prewarmed_value is not None

    def start_prewarm(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> bool:
        """Speculatively kick off a background condensation task.

        Returns True when a new task was scheduled, False when one is
        already running, a result is already cached, or the pre-warm
        cooldown has not elapsed yet. The caller supplies a no-arg
        coroutine factory so this monitor stays decoupled from the
        compactor implementation.

        On task completion the result is stashed in :attr:`_prewarmed_value`
        for the next agent turn boundary to consume via
        :meth:`consume_prewarmed`. Failures are swallowed (logged) so a
        flaky pre-warm never breaks the foreground loop.
        """
        if self.is_prewarming or self.has_prewarmed:
            return False
        if self._last_prewarm_at > 0:
            elapsed = time.monotonic() - self._last_prewarm_at
            if elapsed < self._prewarm_cooldown_s:
                return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug('start_prewarm called outside an event loop; skipping')
            return False
        task = loop.create_task(self._run_prewarm(coro_factory))
        self._prewarm_task = task
        return True

    async def _run_prewarm(self, coro_factory: Callable[[], Awaitable[Any]]) -> None:
        started = time.monotonic()
        try:
            self._prewarmed_value = await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug('Background condensation pre-warm failed', exc_info=True)
            self._prewarmed_value = None
        finally:
            self._last_prewarm_at = time.monotonic()
            duration = self._last_prewarm_at - started
            if duration >= 0:
                # Pre-warm timings are equally good signal for the ETA model.
                self._condense_durations.append(duration)

    def consume_prewarmed(self) -> Any:
        """Return and clear the pending pre-warmed condensation result.

        Should be called by the foreground compaction path on the next
        agent turn boundary (Phase 3.12). Returns ``None`` when nothing
        is ready.
        """
        value = self._prewarmed_value
        self._prewarmed_value = None
        if value is not None:
            # Treat consumption as a synchronous condensation event for
            # cooldown purposes — the agent has now "seen" the new summary.
            self._condensation_count += 1
            self._last_condensation_at = time.monotonic()
        return value

    # ------------------------------------------------------------------ #
    # Phase 3.13 — rolling P50 ETA
    # ------------------------------------------------------------------ #

    def eta_seconds(self) -> float | None:
        """Return the rolling-P50 condensation duration in seconds.

        ``None`` when fewer than 3 samples have been observed (the
        estimator is not yet trustworthy). Callers should treat this as
        a soft hint, not a hard guarantee.
        """
        if len(self._condense_durations) < 3:
            return None
        try:
            return float(statistics.median(self._condense_durations))
        except statistics.StatisticsError:
            return None

    def pressure_ratio(self) -> float:
        """Return memory pressure as 0.0 (none) to 1.0 (at/above critical).

        Linear interpolation between the warning and critical thresholds.
        Returns 0.0 when psutil is unavailable or sampling fails.
        """
        rss = self._sample_rss()
        if rss is None:
            return 0.0
        if rss >= self._crit_mb:
            return 1.0
        if rss <= self._warn_mb:
            return 0.0
        return (rss - self._warn_mb) / (self._crit_mb - self._warn_mb)

    def snapshot(self) -> dict[str, Any]:
        """Return diagnostic snapshot for debug endpoints."""
        return {
            'rss_mb': self._last_rss_mb,
            'baseline_rss_mb': self._baseline_rss_mb,
            'warn_threshold_mb': self._warn_mb,
            'crit_threshold_mb': self._crit_mb,
            'warn_delta_mb': self._warn_delta_mb,
            'crit_delta_mb': self._crit_delta_mb,
            'cooldown_s': self._cooldown_s,
            'prewarm_cooldown_s': self._prewarm_cooldown_s,
            'min_history_events': self._min_history_events,
            'condensation_count': self._condensation_count,
            'psutil_available': _HAS_PSUTIL,
            'level': self._level_str(),
            'is_prewarming': self.is_prewarming,
            'has_prewarmed': self.has_prewarmed,
            'eta_seconds_p50': self.eta_seconds(),
            'condense_samples': len(self._condense_durations),
            'prewarm_ratio': self._prewarm_ratio,
            'signal_ratio': self._signal_ratio,
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
            logger.debug('Failed to read RSS', exc_info=True)
            return None

    def _level_str(self) -> str:
        if self._last_rss_mb >= self._crit_mb:
            return 'critical'
        if self._last_rss_mb >= self._warn_mb:
            return 'warning'
        return 'normal'
