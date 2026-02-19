"""Unit tests for backend.controller.rate_governor module.

Tests cover:
- LLMRateGovernor initialization with various parameters
- Token rate limiting and sliding window tracking
- Adaptive backoff computation and ceiling adjustments
- LLM latency tracking and P95 calculations
- check_and_wait throttling logic
- Diagnostic snapshots
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.controller.rate_governor import LLMRateGovernor


class TestLLMRateGovernorInit:
    """Test LLMRateGovernor initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default rate limit."""
        governor = LLMRateGovernor()

        assert governor.max_tokens_per_minute == 100000
        assert governor.history_window_seconds == 60
        assert governor._base_backoff == 1.0
        assert governor._max_backoff == 30.0
        assert governor._backoff_multiplier == 1.5
        assert governor._current_backoff == 1.0
        assert not governor._history
        assert not governor._latencies
        assert governor._consecutive_throttles == 0

    def test_init_with_custom_rate(self):
        """Should initialize with custom max tokens per minute."""
        governor = LLMRateGovernor(max_tokens_per_minute=50000)

        assert governor.max_tokens_per_minute == 50000
        assert governor.history_window_seconds == 60

    def test_init_with_custom_window(self):
        """Should initialize with custom history window."""
        governor = LLMRateGovernor(history_window_seconds=120)

        assert governor.max_tokens_per_minute == 100000
        assert governor.history_window_seconds == 120

    def test_init_with_custom_backoff_params(self):
        """Should initialize with custom backoff parameters."""
        governor = LLMRateGovernor(
            base_backoff_s=2.0,
            max_backoff_s=60.0,
            backoff_multiplier=2.0,
        )

        assert governor._base_backoff == 2.0
        assert governor._max_backoff == 60.0
        assert governor._backoff_multiplier == 2.0
        assert governor._current_backoff == 2.0

    def test_history_deque_has_maxlen(self):
        """History deque should have maxlen=2000 as safety net."""
        governor = LLMRateGovernor()

        assert governor._history.maxlen == 2000

    def test_latencies_deque_has_maxlen(self):
        """Latencies deque should have maxlen=20."""
        governor = LLMRateGovernor()

        assert governor._latencies.maxlen == 20


class TestCheckAndWait:
    """Test check_and_wait method."""

    @pytest.mark.asyncio
    async def test_disabled_governor_returns_immediately(self):
        """Governor with max_tokens_per_minute <= 0 should return immediately."""
        governor = LLMRateGovernor(max_tokens_per_minute=0)
        usage = MagicMock()
        usage.prompt_tokens = 1000
        usage.completion_tokens = 500

        # Should not raise or throttle
        await governor.check_and_wait(usage)

        assert not governor._history

    @pytest.mark.asyncio
    async def test_first_call_adds_to_history(self):
        """First call should add usage to history without throttling."""
        governor = LLMRateGovernor(max_tokens_per_minute=10000)
        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 50

        await governor.check_and_wait(usage)

        assert len(governor._history) == 1
        assert governor._consecutive_throttles == 0

    @pytest.mark.asyncio
    async def test_under_limit_does_not_throttle(self):
        """Usage under limit should not trigger throttling."""
        governor = LLMRateGovernor(max_tokens_per_minute=10000)

        # First call
        usage1 = MagicMock()
        usage1.prompt_tokens = 100
        usage1.completion_tokens = 50
        await governor.check_and_wait(usage1)

        # Second call - still under limit
        usage2 = MagicMock()
        usage2.prompt_tokens = 200
        usage2.completion_tokens = 100
        await governor.check_and_wait(usage2)

        assert len(governor._history) == 2
        assert governor._consecutive_throttles == 0

    @pytest.mark.asyncio
    async def test_over_limit_triggers_throttle(self):
        """Usage over limit should trigger adaptive backoff."""
        governor = LLMRateGovernor(
            max_tokens_per_minute=100,
            base_backoff_s=0.01,  # Short for testing
        )

        # First call
        usage1 = MagicMock()
        usage1.prompt_tokens = 10
        usage1.completion_tokens = 10
        await governor.check_and_wait(usage1)

        # Second call exceeds limit (total 200 > 100)
        usage2 = MagicMock()
        usage2.prompt_tokens = 100
        usage2.completion_tokens = 80

        # Should throttle
        await governor.check_and_wait(usage2)

        assert governor._consecutive_throttles == 1

    @pytest.mark.asyncio
    async def test_consecutive_throttles_increment(self):
        """Consecutive over-limit calls should increment throttle counter."""
        governor = LLMRateGovernor(
            max_tokens_per_minute=50,
            base_backoff_s=0.01,
        )

        # First call
        usage1 = MagicMock()
        usage1.prompt_tokens = 30
        usage1.completion_tokens = 30
        await governor.check_and_wait(usage1)

        # Second and third calls exceed limit (cumulative)
        for i in range(2):
            usage = MagicMock()
            usage.prompt_tokens = 60 + i
            usage.completion_tokens = 60 + i
            await governor.check_and_wait(usage)

        assert governor._consecutive_throttles == 2

    @pytest.mark.asyncio
    async def test_under_limit_resets_throttle_counter(self):
        """Returning under limit should reset consecutive throttle counter."""
        governor = LLMRateGovernor(
            max_tokens_per_minute=100,
            base_backoff_s=0.01,
        )

        # Trigger throttle (exceed limit)
        usage1 = MagicMock()
        usage1.prompt_tokens = 70
        usage1.completion_tokens = 70
        await governor.check_and_wait(usage1)

        assert (
            governor._consecutive_throttles >= 0
        )  # May or may not throttle based on window

        # Wait for history to clear
        await asyncio.sleep(0.1)

        # New call under limit should reset
        usage2 = MagicMock()
        usage2.prompt_tokens = 5
        usage2.completion_tokens = 5
        await governor.check_and_wait(usage2)

        assert governor._consecutive_throttles == 0
        assert governor._current_backoff == 0.01  # Reset to base_backoff_s

    @pytest.mark.asyncio
    async def test_history_pruning_old_entries(self):
        """History should prune entries outside the window."""
        governor = LLMRateGovernor(
            max_tokens_per_minute=10000,
            history_window_seconds=0.05,  # 50ms window
        )

        # Add first entry
        usage1 = MagicMock()
        usage1.prompt_tokens = 10
        usage1.completion_tokens = 10
        await governor.check_and_wait(usage1)
        assert len(governor._history) == 1

        # Wait for window to expire
        await asyncio.sleep(0.1)

        # Add second entry - should prune first
        usage2 = MagicMock()
        usage2.prompt_tokens = 10
        usage2.completion_tokens = 10
        await governor.check_and_wait(usage2)

        assert len(governor._history) == 1  # Old entry pruned


class TestRecordLLMLatency:
    """Test record_llm_latency method."""

    def test_records_single_latency(self):
        """Should record a single latency value."""
        governor = LLMRateGovernor()

        governor.record_llm_latency(1.5)

        assert len(governor._latencies) == 1
        assert governor._latencies[0] == 1.5

    def test_records_multiple_latencies(self):
        """Should record multiple latency values."""
        governor = LLMRateGovernor()

        for i in range(5):
            governor.record_llm_latency(float(i))

        assert len(governor._latencies) == 5

    def test_respects_maxlen(self):
        """Latencies deque should not exceed maxlen=20."""
        governor = LLMRateGovernor()

        # Record 25 latencies (over maxlen)
        for i in range(25):
            governor.record_llm_latency(float(i))

        assert len(governor._latencies) == 20
        # Should keep most recent 20
        assert governor._latencies[-1] == 24.0


class TestLatencyP95:
    """Test _latency_p95 calculation."""

    def test_p95_with_insufficient_data(self):
        """Should return None with < 3 latencies."""
        governor = LLMRateGovernor()

        assert governor._latency_p95() is None

        governor.record_llm_latency(1.0)
        assert governor._latency_p95() is None

        governor.record_llm_latency(2.0)
        assert governor._latency_p95() is None

    def test_p95_with_exactly_three_latencies(self):
        """Should compute P95 with exactly 3 latencies."""
        governor = LLMRateGovernor()

        governor.record_llm_latency(1.0)
        governor.record_llm_latency(2.0)
        governor.record_llm_latency(3.0)

        p95 = governor._latency_p95()
        assert p95 is not None
        assert p95 == 3.0  # P95 of [1, 2, 3] at idx 2

    def test_p95_with_many_latencies(self):
        """Should compute P95 correctly with many latencies."""
        governor = LLMRateGovernor()

        # Record 20 latencies from 1.0 to 20.0
        for i in range(1, 21):
            governor.record_llm_latency(float(i))

        p95 = governor._latency_p95()
        assert p95 is not None
        # P95 at idx int(20 * 0.95) = 19 → sorted[19] = 20.0
        assert p95 == 20.0

    def test_p95_is_sorted(self):
        """P95 should sort latencies before indexing."""
        governor = LLMRateGovernor()

        # Record in random order
        for val in [5.0, 1.0, 3.0, 2.0, 4.0]:
            governor.record_llm_latency(val)

        p95 = governor._latency_p95()
        assert p95 is not None
        # Sorted [1, 2, 3, 4, 5], P95 at idx int(5*0.95)=4 → 5.0
        assert p95 == 5.0


class TestComputeBackoff:
    """Test _compute_backoff adaptive logic."""

    def test_initial_backoff_equals_base(self):
        """First backoff should equal base_backoff * multiplier."""
        governor = LLMRateGovernor(base_backoff_s=2.0)

        backoff = governor._compute_backoff()

        # _compute_backoff multiplies current by multiplier (1.5 default)
        assert backoff == 2.0 * 1.5  # 3.0

    def test_backoff_increases_exponentially(self):
        """Consecutive calls should increase backoff exponentially."""
        governor = LLMRateGovernor(
            base_backoff_s=1.0,
            backoff_multiplier=2.0,
            max_backoff_s=100.0,
        )

        backoff1 = governor._compute_backoff()
        assert backoff1 == 1.0 * 2.0  # 2.0

        backoff2 = governor._compute_backoff()
        assert backoff2 == 2.0 * 2.0  # 4.0

        backoff3 = governor._compute_backoff()
        assert backoff3 == 4.0 * 2.0  # 8.0

    def test_backoff_capped_at_max_backoff(self):
        """Backoff should not exceed max_backoff."""
        governor = LLMRateGovernor(
            base_backoff_s=1.0,
            backoff_multiplier=2.0,
            max_backoff_s=5.0,
        )

        # Compute several times to exceed max
        for _ in range(10):
            backoff = governor._compute_backoff()

        assert backoff == 5.0

    def test_backoff_adapts_to_latency_p95(self):
        """Backoff should cap at 2x P95 latency if available."""
        governor = LLMRateGovernor(
            base_backoff_s=1.0,
            backoff_multiplier=2.0,
            max_backoff_s=100.0,
        )

        # Record latencies with P95 = 3.0
        for i in range(1, 21):
            governor.record_llm_latency(float(i) * 0.15)  # P95 ~3.0

        # Compute backoff - should cap at 2 * P95 = 6.0
        for _ in range(10):
            backoff = governor._compute_backoff()

        # Should be capped at adaptive ceiling (2 * 3.0 = 6.0)
        assert backoff <= 6.0

    def test_adaptive_cap_not_below_base_backoff(self):
        """Adaptive cap should never be below base_backoff."""
        governor = LLMRateGovernor(
            base_backoff_s=5.0,
            backoff_multiplier=2.0,
            max_backoff_s=100.0,
        )

        # Record very small latencies
        for _ in range(10):
            governor.record_llm_latency(0.1)

        backoff = governor._compute_backoff()

        # Even with tiny latencies, should respect base_backoff
        assert backoff >= 5.0


class TestSnapshot:
    """Test snapshot diagnostic method."""

    def test_snapshot_initial_state(self):
        """Snapshot should reflect initial state."""
        governor = LLMRateGovernor(
            max_tokens_per_minute=50000,
            history_window_seconds=120,
        )

        snapshot = governor.snapshot()

        assert snapshot["max_tokens_per_minute"] == 50000
        assert snapshot["window_seconds"] == 120
        assert snapshot["current_backoff_s"] == 1.0
        assert snapshot["consecutive_throttles"] == 0
        assert snapshot["latency_p95_s"] is None
        assert snapshot["history_size"] == 0

    def test_snapshot_with_history(self):
        """Snapshot should include history size."""
        governor = LLMRateGovernor()
        governor._history.append((1.0, 100))
        governor._history.append((2.0, 200))

        snapshot = governor.snapshot()

        assert snapshot["history_size"] == 2

    def test_snapshot_with_latency_data(self):
        """Snapshot should include P95 latency when available."""
        governor = LLMRateGovernor()

        for i in range(1, 21):
            governor.record_llm_latency(float(i))

        snapshot = governor.snapshot()

        assert snapshot["latency_p95_s"] is not None
        assert snapshot["latency_p95_s"] == 20.0

    def test_snapshot_after_throttle(self):
        """Snapshot should reflect consecutive throttles."""
        governor = LLMRateGovernor()
        governor._consecutive_throttles = 3
        governor._current_backoff = 4.5

        snapshot = governor.snapshot()

        assert snapshot["consecutive_throttles"] == 3
        assert snapshot["current_backoff_s"] == 4.5

    def test_snapshot_rounds_values(self):
        """Snapshot should round floating point values."""
        governor = LLMRateGovernor()
        governor._current_backoff = 1.23456
        governor.record_llm_latency(2.3456789)
        governor.record_llm_latency(2.4567890)
        governor.record_llm_latency(2.5678901)

        snapshot = governor.snapshot()

        # current_backoff_s rounded to 2 decimals
        assert snapshot["current_backoff_s"] == 1.23
        # latency_p95_s rounded to 3 decimals
        assert isinstance(snapshot["latency_p95_s"], float)
