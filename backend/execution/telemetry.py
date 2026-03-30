from __future__ import annotations

from collections import Counter

from backend.core.logger import app_logger as logger

runtime_telemetry: RuntimeTelemetry  # forward ref for type checking


class RuntimeTelemetry:
    def __init__(self) -> None:
        self._acquire_counter: Counter[str] = Counter()
        self._reuse_counter: Counter[str] = Counter()
        self._release_counter: Counter[str] = Counter()
        self._watchdog_counter: Counter[tuple[str, str]] = Counter()
        self._scaling_counter: Counter[str] = Counter()

    def record_acquire(self, key: str, reused: bool) -> None:
        self._acquire_counter[key] += 1
        if reused:
            self._reuse_counter[key] += 1
        logger.debug(
            "[RuntimeTelemetry] acquire key=%s reused=%s counts=%s",
            key,
            reused,
            dict(self._acquire_counter),
        )

    def record_release(self, key: str) -> None:
        self._release_counter[key] += 1
        logger.debug(
            "[RuntimeTelemetry] release key=%s counts=%s",
            key,
            dict(self._release_counter),
        )

    def record_watchdog_termination(self, key: str, reason: str) -> None:
        self._watchdog_counter[(key, reason)] += 1
        logger.warning(
            "[RuntimeTelemetry] watchdog terminated runtime key=%s reason=%s",
            key,
            reason,
        )

    def record_scaling_signal(self, signal: str, *, severity: str = "info") -> None:
        self._scaling_counter[signal] += 1
        log_fn = logger.info if severity == "info" else logger.warning
        log_fn(
            "[RuntimeTelemetry] scaling signal=%s severity=%s count=%s",
            signal,
            severity,
            self._scaling_counter[signal],
        )

    def snapshot(self) -> dict[str, dict[str, int]]:
        watchdog = {
            f"{key}|{reason}": count
            for (key, reason), count in self._watchdog_counter.items()
        }
        return {
            "acquire": dict(self._acquire_counter),
            "reuse": dict(self._reuse_counter),
            "release": dict(self._release_counter),
            "watchdog": watchdog,
            "scaling": dict(self._scaling_counter),
        }

    def reset(self) -> None:
        self._acquire_counter.clear()
        self._reuse_counter.clear()
        self._release_counter.clear()
        self._watchdog_counter.clear()
        self._scaling_counter.clear()


runtime_telemetry = RuntimeTelemetry()
