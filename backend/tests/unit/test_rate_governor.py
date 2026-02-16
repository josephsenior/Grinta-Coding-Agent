"""Unit tests for backend.controller.rate_governor — LLM token rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.controller.rate_governor import LLMRateGovernor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_usage(prompt: int = 0, completion: int = 0):
    """Build a minimal TokenUsage-like object."""
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self):
        gov = LLMRateGovernor()
        assert gov.max_tokens_per_minute == 100_000
        assert gov.history_window_seconds == 60
        assert gov._base_backoff == 1.0
        assert gov._max_backoff == 30.0
        assert gov._backoff_multiplier == 1.5
        assert gov._consecutive_throttles == 0

    def test_custom_params(self):
        gov = LLMRateGovernor(
            max_tokens_per_minute=50_000,
            history_window_seconds=30,
            base_backoff_s=0.5,
            max_backoff_s=10.0,
            backoff_multiplier=2.0,
        )
        assert gov.max_tokens_per_minute == 50_000
        assert gov.history_window_seconds == 30
        assert gov._base_backoff == 0.5
        assert gov._max_backoff == 10.0
        assert gov._backoff_multiplier == 2.0


# ---------------------------------------------------------------------------
# check_and_wait — under limit
# ---------------------------------------------------------------------------


class TestCheckAndWaitUnderLimit:
    @pytest.mark.asyncio
    async def test_no_throttle_under_limit(self):
        gov = LLMRateGovernor(max_tokens_per_minute=100_000)
        usage = _token_usage(prompt=500, completion=500)
        # Should complete instantly — no sleep
        await gov.check_and_wait(usage)
        assert gov._consecutive_throttles == 0

    @pytest.mark.asyncio
    async def test_single_data_point_no_throttle(self):
        gov = LLMRateGovernor(max_tokens_per_minute=1)
        # Only one history entry → can't compare → no throttle
        usage = _token_usage(prompt=10_000, completion=10_000)
        await gov.check_and_wait(usage)
        assert gov._consecutive_throttles == 0

    @pytest.mark.asyncio
    async def test_zero_limit_skips_check(self):
        gov = LLMRateGovernor(max_tokens_per_minute=0)
        usage = _token_usage(prompt=999_999, completion=999_999)
        await gov.check_and_wait(usage)
        assert gov._consecutive_throttles == 0


# ---------------------------------------------------------------------------
# check_and_wait — over limit
# ---------------------------------------------------------------------------


class TestCheckAndWaitOverLimit:
    @pytest.mark.asyncio
    async def test_throttle_when_over_limit(self):
        gov = LLMRateGovernor(
            max_tokens_per_minute=100,
            base_backoff_s=0.01,
            max_backoff_s=0.05,
        )
        # First call sets up the history
        await gov.check_and_wait(_token_usage(0, 0))
        # Second call with huge jump
        await gov.check_and_wait(_token_usage(prompt=200, completion=200))
        assert gov._consecutive_throttles >= 1

    @pytest.mark.asyncio
    async def test_consecutive_throttles_increment(self):
        gov = LLMRateGovernor(
            max_tokens_per_minute=10,
            base_backoff_s=0.001,
            max_backoff_s=0.01,
        )
        await gov.check_and_wait(_token_usage(0, 0))
        await gov.check_and_wait(_token_usage(100, 100))
        first = gov._consecutive_throttles
        await gov.check_and_wait(_token_usage(200, 200))
        assert gov._consecutive_throttles >= first

    @pytest.mark.asyncio
    async def test_throttle_resets_when_under_limit(self):
        gov = LLMRateGovernor(
            max_tokens_per_minute=100,
            base_backoff_s=0.001,
            max_backoff_s=0.01,
        )
        # Trigger throttle
        await gov.check_and_wait(_token_usage(0, 0))
        await gov.check_and_wait(_token_usage(200, 200))
        assert gov._consecutive_throttles >= 1

        # Reset history and stay under limit
        gov._history.clear()
        gov._consecutive_throttles = 1  # simulate previous throttle
        await gov.check_and_wait(_token_usage(1, 1))
        # Only one entry — can't throttle
        # On next call with same value → zero delta
        await gov.check_and_wait(_token_usage(1, 1))
        assert gov._consecutive_throttles == 0


# ---------------------------------------------------------------------------
# History pruning
# ---------------------------------------------------------------------------


class TestHistoryPruning:
    @pytest.mark.asyncio
    async def test_old_entries_pruned(self):
        gov = LLMRateGovernor(
            max_tokens_per_minute=100_000,
            history_window_seconds=5,
        )
        # Insert old entry
        gov._history.append((time.time() - 100, 0))
        gov._history.append((time.time() - 100, 50))

        await gov.check_and_wait(_token_usage(100, 0))
        # Old entries should have been pruned
        assert all(
            time.time() - ts < 10 for ts, _ in gov._history
        )


# ---------------------------------------------------------------------------
# Latency recording & P95
# ---------------------------------------------------------------------------


class TestLatencyTracking:
    def test_record_latency(self):
        gov = LLMRateGovernor()
        gov.record_llm_latency(0.5)
        gov.record_llm_latency(1.0)
        gov.record_llm_latency(1.5)
        assert len(gov._latencies) == 3

    def test_p95_with_enough_data(self):
        gov = LLMRateGovernor()
        for i in range(20):
            gov.record_llm_latency(float(i))
        p95 = gov._latency_p95()
        assert p95 is not None
        assert p95 >= 17.0  # 95th percentile of 0..19

    def test_p95_insufficient_data(self):
        gov = LLMRateGovernor()
        gov.record_llm_latency(1.0)
        gov.record_llm_latency(2.0)
        assert gov._latency_p95() is None  # needs >= 3


# ---------------------------------------------------------------------------
# Adaptive backoff
# ---------------------------------------------------------------------------


class TestAdaptiveBackoff:
    def test_exponential_increase(self):
        gov = LLMRateGovernor(
            base_backoff_s=1.0,
            max_backoff_s=100.0,
            backoff_multiplier=2.0,
        )
        b1 = gov._compute_backoff()
        b2 = gov._compute_backoff()
        assert b2 > b1
        assert b2 == pytest.approx(b1 * 2.0)

    def test_capped_at_max(self):
        gov = LLMRateGovernor(
            base_backoff_s=1.0,
            max_backoff_s=5.0,
            backoff_multiplier=10.0,
        )
        for _ in range(20):
            backoff = gov._compute_backoff()
        assert backoff <= 5.0

    def test_adaptive_cap_from_latency(self):
        gov = LLMRateGovernor(
            base_backoff_s=1.0,
            max_backoff_s=100.0,
            backoff_multiplier=2.0,
        )
        # Record low latencies
        for _ in range(5):
            gov.record_llm_latency(0.5)
        # Backoff should be capped at 2 * p95
        for _ in range(10):
            gov._compute_backoff()
        # After many iterations, should be capped near 2 * 0.5 = 1.0
        final = gov._current_backoff
        assert final <= 2.0  # 2x the p95 latency


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_fields(self):
        gov = LLMRateGovernor(max_tokens_per_minute=50_000)
        snap = gov.snapshot()
        assert snap["max_tokens_per_minute"] == 50_000
        assert snap["window_seconds"] == 60
        assert "current_backoff_s" in snap
        assert "consecutive_throttles" in snap
        assert "latency_p95_s" in snap
        assert "history_size" in snap

    def test_snapshot_latency_none_when_insufficient(self):
        gov = LLMRateGovernor()
        snap = gov.snapshot()
        assert snap["latency_p95_s"] is None

    def test_snapshot_reflects_latency(self):
        gov = LLMRateGovernor()
        for i in range(10):
            gov.record_llm_latency(float(i))
        snap = gov.snapshot()
        assert snap["latency_p95_s"] is not None
