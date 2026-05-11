"""Rate governor for LLM token usage with adaptive backoff."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.inference.metrics import TokenUsage


class LLMRateGovernor:
    """Governs the rate of token consumption by the agent.

    Prevents runaway costs and rate limit errors by throttling execution
    when token usage exceeds a configured rate.  Uses **adaptive backoff**
    based on observed LLM response latency instead of a fixed sleep.
    """

    def __init__(
        self,
        max_tokens_per_minute: int = 100000,
        history_window_seconds: int = 60,
        *,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        backoff_multiplier: float = 1.5,
    ) -> None:
        self.max_tokens_per_minute = max_tokens_per_minute
        self.history_window_seconds = history_window_seconds
        # Adaptive backoff params
        self._base_backoff = base_backoff_s
        self._max_backoff = max_backoff_s
        self._backoff_multiplier = backoff_multiplier
        self._current_backoff = base_backoff_s
        # Token usage sliding window: (timestamp, cumulative_token_count)
        # maxlen=2000 is a safety net; time-based pruning is the primary bound.
        self._history: deque[tuple[float, int]] = deque(maxlen=2000)
        # LLM latency tracking for adaptive ceiling
        self._latencies: deque[float] = deque(maxlen=20)
        self._consecutive_throttles: int = 0
        self._memory_pressure_factor: float = 1.0
        # Observed TPM ceiling per ``(provider, model)`` derived from past 429s
        # tagged as ``RateLimitKind.TPM``. We learn the ceiling so we can
        # pre-emptively throttle below it without waiting for another 429.
        # Stores the *most conservative* (smallest) observed limit per key.
        self._observed_tpm_ceiling: dict[tuple[str, str], int] = {}
        self._observed_tpm_ceiling_max: int = 20

    def record_rate_limit_event(
        self,
        *,
        provider: str | None,
        model: str | None,
        kind: Any,
        tokens_in_last_window: int | None = None,
    ) -> None:
        """Learn from a provider 429 so future calls can throttle proactively.

        Called by the LLM client layer after a ``RateLimitError`` is mapped.
        Only TPM events update the observed ceiling; other kinds are ignored
        because they are not bounded by the token budget this governor tracks.
        ``tokens_in_last_window`` may be supplied when the caller knows the
        actual window usage; otherwise the governor uses its own history.
        """
        try:
            from backend.inference.exceptions import RateLimitKind
        except Exception:
            return
        if kind is not RateLimitKind.TPM:
            return
        prov = (provider or '').lower()
        mdl = (model or '').lower()
        if not prov or not mdl:
            return
        if tokens_in_last_window is None and self._history:
            _, oldest = self._history[0]
            current = self._history[-1][1]
            tokens_in_last_window = max(0, current - oldest)
        if not tokens_in_last_window or tokens_in_last_window <= 0:
            return
        # Treat the observed usage at the time of the 429 as a soft ceiling.
        # Apply a 5% safety margin so we throttle a touch earlier next time.
        ceiling = max(1, int(tokens_in_last_window * 0.95))
        key = (prov, mdl)
        prev = self._observed_tpm_ceiling.get(key)
        if prev is None or ceiling < prev:
            self._observed_tpm_ceiling[key] = ceiling
            if len(self._observed_tpm_ceiling) > self._observed_tpm_ceiling_max:
                oldest_keys = list(self._observed_tpm_ceiling.keys())[
                    : len(self._observed_tpm_ceiling) - self._observed_tpm_ceiling_max
                ]
                for k in oldest_keys:
                    del self._observed_tpm_ceiling[k]
            logger.info(
                'Learned TPM ceiling for %s/%s: %d tokens/%ds (was %s)',
                prov,
                mdl,
                ceiling,
                self.history_window_seconds,
                prev,
            )

    def set_memory_pressure_factor(self, factor: float) -> None:
        """Set a memory-pressure scaling factor [0.0, 1.0].

        When the system is under memory pressure this factor reduces the
        effective TPM limit so the agent generates fewer tokens, giving
        condensation time to catch up.  1.0 = no pressure, 0.0 = full stop.
        """
        self._memory_pressure_factor = max(0.0, min(1.0, factor))

    def effective_tpm_limit(
        self, *, provider: str | None = None, model: str | None = None
    ) -> int:
        """Return the effective TPM limit.

        Applies learned per-model ceiling and the memory-pressure factor.
        """
        configured = self.max_tokens_per_minute
        if configured <= 0:
            return 0
        if not provider or not model:
            return max(1, int(configured * self._memory_pressure_factor))
        learned = self._observed_tpm_ceiling.get((provider.lower(), model.lower()))
        if learned is not None:
            configured = min(configured, learned)
        return max(1, int(configured * self._memory_pressure_factor))

    async def check_and_wait(
        self,
        current_usage: TokenUsage,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Check current rate and apply adaptive backoff if necessary.

        ``provider`` and ``model`` are optional; when supplied, the governor
        compares the sliding-window usage against the smaller of the
        configured ``max_tokens_per_minute`` and any per-model TPM ceiling
        learned from past 429s, throttling pre-emptively below that bound.
        """
        effective_limit = self.effective_tpm_limit(provider=provider, model=model)
        if effective_limit <= 0:
            return

        now = time.time()
        current_total = current_usage.prompt_tokens + current_usage.completion_tokens

        # Prune history outside window
        while self._history and now - self._history[0][0] > self.history_window_seconds:
            self._history.popleft()

        self._history.append((now, current_total))

        if len(self._history) < 2:
            return

        _, oldest_total = self._history[0]
        usage_in_window = current_total - oldest_total

        if usage_in_window > effective_limit:
            self._consecutive_throttles += 1
            wait_s = self._compute_backoff()
            logger.warning(
                'Token rate limit exceeded (%d tokens in last %ds). Limit: %d/min%s. Throttling %.1fs (consecutive=%d)',
                usage_in_window,
                self.history_window_seconds,
                effective_limit,
                ' [learned]' if effective_limit != self.max_tokens_per_minute else '',
                wait_s,
                self._consecutive_throttles,
            )
            await asyncio.sleep(wait_s)
        else:
            # Reset backoff on healthy iteration
            if self._consecutive_throttles > 0:
                self._consecutive_throttles = 0
                self._current_backoff = self._base_backoff

    def record_llm_latency(self, latency_s: float) -> None:
        """Record an LLM call latency for adaptive ceiling adjustment."""
        self._latencies.append(latency_s)

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for debug endpoints."""
        p95 = self._latency_p95()
        return {
            'max_tokens_per_minute': self.max_tokens_per_minute,
            'window_seconds': self.history_window_seconds,
            'current_backoff_s': round(self._current_backoff, 2),
            'consecutive_throttles': self._consecutive_throttles,
            'memory_pressure_factor': self._memory_pressure_factor,
            'latency_p95_s': round(p95, 3) if p95 else None,
            'history_size': len(self._history),
            'observed_tpm_ceilings': {
                f'{p}/{m}': v for (p, m), v in self._observed_tpm_ceiling.items()
            },
        }

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _compute_backoff(self) -> float:
        """Compute adaptive backoff duration.

        Strategy:
        1. Exponential increase per consecutive throttle.
        2. Cap at max_backoff or 2x the P95 LLM latency (whichever is smaller)
           so we never sleep longer than two typical LLM calls.
        """
        self._current_backoff = min(
            self._current_backoff * self._backoff_multiplier,
            self._max_backoff,
        )
        # Adapt ceiling to observed LLM latency
        p95 = self._latency_p95()
        if p95 and p95 > 0:
            adaptive_cap = max(self._base_backoff, p95 * 2)
            self._current_backoff = min(self._current_backoff, adaptive_cap)

        return self._current_backoff

    def _latency_p95(self) -> float | None:
        """Return the P95 latency from recent observations."""
        if len(self._latencies) < 3:
            return None
        sorted_lats = sorted(self._latencies)
        idx = int(len(sorted_lats) * 0.95)
        return sorted_lats[min(idx, len(sorted_lats) - 1)]
