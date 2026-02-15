from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.core.constants import (
    EVICTION_SPIKE_THRESHOLD,
    IDLE_RECLAIM_SPIKE_THRESHOLD,
)
from backend.core.logger import FORGE_logger as logger
from backend.runtime.pool import (
    PooledRuntime,
    RuntimePool,
    WarmPoolPolicy,
    WarmRuntimePool,
)
from backend.runtime.telemetry import RuntimeTelemetry, runtime_telemetry
from backend.runtime.watchdog import runtime_watchdog

if TYPE_CHECKING:
    from backend.controller.agent import Agent
    from backend.core.config import ForgeConfig
    from backend.events.stream import EventStream
    from backend.llm.llm_registry import LLMRegistry
    from backend.runtime.base import Runtime


@dataclass(slots=True)
class RuntimeAcquireResult:
    runtime: Runtime
    repo_directory: str | None = None


class RuntimeOrchestrator:
    """Runtime orchestration wrapper (single-use + pluggable pools)."""

    def __init__(
        self,
        pool: RuntimePool | None = None,
        telemetry: RuntimeTelemetry | None = None,
    ) -> None:
        self._pool = pool or WarmRuntimePool()
        self._telemetry = telemetry or runtime_telemetry
        runtime_watchdog.set_idle_cleanup(self._pool)
        self._pool_policy_fingerprint: str | None = None
        self._default_pool_policy: WarmPoolPolicy | None = None
        self._key_pool_policies: dict[str, WarmPoolPolicy] = {}
        self._pool_policy_snapshot: tuple[WarmPoolPolicy, dict[str, WarmPoolPolicy]] | None = None
        self._last_idle_reclaim_totals: dict[str, int] = {}
        self._last_eviction_totals: dict[str, int] = {}
        self._saturated_keys: set[str] = set()

    def acquire(
        self,
        config: ForgeConfig,
        llm_registry: LLMRegistry,
        *,
        session_id: str | None = None,
        agent: Agent,
        headless_mode: bool,
        vcs_provider_tokens,
        repo_initializer: Callable[[Runtime], str | None] | None = None,
        event_stream: EventStream | None = None,
        env_vars: dict[str, str] | None = None,
        user_id: str | None = None,
    ) -> RuntimeAcquireResult:
        from backend.core.setup import create_runtime  # lazy import to avoid cycles

        key = config.runtime
        pooled = self._pool.acquire(key)
        if pooled:
            self._telemetry.record_acquire(key, reused=True)
            result = RuntimeAcquireResult(runtime=pooled.runtime, repo_directory=pooled.repo_directory)
            runtime_watchdog.watch_runtime(
                result.runtime,
                key=key,
                session_id=session_id,
            )
            return result

        runtime = create_runtime(
            config,
            llm_registry=llm_registry,
            sid=session_id,
            headless_mode=headless_mode,
            agent=agent,
            vcs_provider_tokens=vcs_provider_tokens,
            event_stream=event_stream,
            env_vars=env_vars,
            user_id=user_id,
        )
        repo_dir = repo_initializer(runtime) if repo_initializer else None
        self._telemetry.record_acquire(key, reused=False)
        result = RuntimeAcquireResult(runtime=runtime, repo_directory=repo_dir)
        runtime_watchdog.watch_runtime(
            result.runtime,
            key=key,
            session_id=session_id,
        )
        return result

    def release(self, result: RuntimeAcquireResult, key: str | None = None) -> None:
        key = key or result.runtime.config.runtime  # type: ignore[attr-defined]
        pooled = PooledRuntime(runtime=result.runtime, repo_directory=result.repo_directory)
        self._pool.release(key, pooled)
        self._telemetry.record_release(key)
        runtime_watchdog.unwatch_runtime(result.runtime)
        self._maybe_emit_scaling_signals()

    def pool_stats(self) -> dict[str, int]:
        return self._pool.stats()

    def _maybe_emit_scaling_signals(self) -> None:
        pool_stats, idle_reclaims, evictions, watched_counts = self._collect_scaling_inputs()
        self._handle_idle_reclaim_spikes(idle_reclaims)
        self._handle_eviction_spikes(evictions)
        self._handle_watchdog_saturation(pool_stats, watched_counts)

    def _collect_scaling_inputs(
        self,
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
        pool_stats = self._pool.stats()
        idle_reclaims = self._pool.idle_reclaim_stats()
        evictions = self._pool.eviction_stats()
        watched_counts = runtime_watchdog.stats()
        return pool_stats, idle_reclaims, evictions, watched_counts

    def _handle_idle_reclaim_spikes(self, idle_reclaims: dict[str, int]) -> None:
        for key, total in idle_reclaims.items():
            self._maybe_record_idle_reclaim_spike(key, total)
        self._prune_missing_keys(self._last_idle_reclaim_totals, idle_reclaims)

    def _maybe_record_idle_reclaim_spike(self, key: str, total: int) -> None:
        previous = self._last_idle_reclaim_totals.get(key, 0)
        delta = total - previous
        if delta >= IDLE_RECLAIM_SPIKE_THRESHOLD:
            signal = f"overprovision|{key}"
            self._telemetry.record_scaling_signal(signal, severity="info")
            logger.info(
                "Idle reclaim spike detected for runtime=%s delta=%s total=%s",
                key,
                delta,
                total,
            )
        self._last_idle_reclaim_totals[key] = total

    def _handle_eviction_spikes(self, evictions: dict[str, int]) -> None:
        for key, total in evictions.items():
            self._maybe_record_eviction_spike(key, total)
        self._prune_missing_keys(self._last_eviction_totals, evictions)

    def _maybe_record_eviction_spike(self, key: str, total: int) -> None:
        previous = self._last_eviction_totals.get(key, 0)
        delta = total - previous
        if delta >= EVICTION_SPIKE_THRESHOLD:
            signal = f"capacity_exhausted|{key}"
            self._telemetry.record_scaling_signal(signal, severity="warning")
            logger.warning(
                "Warm pool eviction spike for runtime=%s delta=%s total=%s",
                key,
                delta,
                total,
            )
        self._last_eviction_totals[key] = total

    def _prune_missing_keys(self, cache: dict[str, int], latest_stats: dict[str, int]) -> None:
        for missing in set(cache) - set(latest_stats):
            cache.pop(missing, None)

    def _policy_for_key(self, key: str) -> WarmPoolPolicy | None:
        """Get the warm pool policy for a given runtime key."""
        if not self._key_pool_policies and self._default_pool_policy is None:
            return None
        return self._key_pool_policies.get(key, self._default_pool_policy)

    def _handle_watchdog_saturation(self, pool_stats: dict[str, int], watched_counts: dict[str, int]) -> None:
        new_saturated: set[str] = set()
        for key, count in watched_counts.items():
            policy = self._policy_for_key(key)
            if self._is_saturated(policy, key, count, pool_stats):
                new_saturated.add(key)
                if key not in self._saturated_keys:
                    signal = f"saturation|{key}"
                    self._telemetry.record_scaling_signal(signal, severity="warning")
                    logger.warning(
                        "Runtime key=%s saturated: active=%s max_size=%s",
                        key,
                        count,
                        policy.max_size if policy else "unknown",
                    )
        self._saturated_keys = new_saturated

    def _is_saturated(
        self,
        policy: WarmPoolPolicy | None,
        key: str,
        active_count: int,
        pool_stats: dict[str, int],
    ) -> bool:
        if not policy or policy.max_size <= 0:
            return False
        if pool_stats.get(key, 0) > 0:
            return False
        return active_count >= policy.max_size

    def idle_reclaim_stats(self) -> dict[str, int]:
        stats_fn = getattr(self._pool, "idle_reclaim_stats", None)
        if callable(stats_fn):
            return stats_fn()
        return {}

    def eviction_stats(self) -> dict[str, int]:
        stats_fn = getattr(self._pool, "eviction_stats", None)
        if callable(stats_fn):
            return stats_fn()
        return {}


runtime_orchestrator = RuntimeOrchestrator()
