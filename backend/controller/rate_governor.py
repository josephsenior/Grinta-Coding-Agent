"""Rate governor for LLM token usage with adaptive backoff."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.llm.metrics import TokenUsage


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

    async def check_and_wait(self, current_usage: TokenUsage) -> None:
        """Check current rate and apply adaptive backoff if necessary."""
        if self.max_tokens_per_minute <= 0:
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

        if usage_in_window > self.max_tokens_per_minute:
            self._consecutive_throttles += 1
            wait_s = self._compute_backoff()
            logger.warning(
                "Token rate limit exceeded (%d tokens in last %ds). Limit: %d/min. Throttling %.1fs (consecutive=%d)",
                usage_in_window,
                self.history_window_seconds,
                self.max_tokens_per_minute,
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
            "max_tokens_per_minute": self.max_tokens_per_minute,
            "window_seconds": self.history_window_seconds,
            "current_backoff_s": round(self._current_backoff, 2),
            "consecutive_throttles": self._consecutive_throttles,
            "latency_p95_s": round(p95, 3) if p95 else None,
            "history_size": len(self._history),
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
