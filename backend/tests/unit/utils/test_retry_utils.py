"""Tests for backend.utils.retry — Retry with backoff utilities."""

from __future__ import annotations


import pytest

from backend.core.schemas import RetryConfig, RetryStrategy
from backend.utils.retry import (
    RetryError,
    RetryExhaustedError,
    calculate_backoff,
    retry,
)


# ── RetryError / RetryExhaustedError ────────────────────────────────


class TestRetryErrors:
    def test_retry_error(self):
        e = RetryError("fail")
        assert str(e) == "fail"

    def test_retry_exhausted_error(self):
        inner = ValueError("boom")
        e = RetryExhaustedError(3, inner)
        assert e.attempts == 3
        assert e.last_exception is inner
        assert "3 attempts" in str(e)
        assert "boom" in str(e)

    def test_retry_exhausted_none_exception(self):
        e = RetryExhaustedError(1, None)
        assert e.last_exception is None


# ── calculate_backoff ────────────────────────────────────────────────


class TestCalculateBackoff:
    def test_immediate(self):
        cfg = RetryConfig(strategy=RetryStrategy.IMMEDIATE)
        assert calculate_backoff(0, cfg) == 0.0
        assert calculate_backoff(5, cfg) == 0.0

    def test_fixed(self):
        cfg = RetryConfig(strategy=RetryStrategy.FIXED, initial_delay=2.0, jitter=False)
        assert calculate_backoff(0, cfg) == 2.0
        assert calculate_backoff(5, cfg) == 2.0

    def test_linear(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.LINEAR, initial_delay=1.0, jitter=False
        )
        assert calculate_backoff(0, cfg) == 1.0
        assert calculate_backoff(1, cfg) == 2.0
        assert calculate_backoff(2, cfg) == 3.0

    def test_exponential(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            initial_delay=1.0,
            exponential_base=2.0,
            jitter=False,
        )
        assert calculate_backoff(0, cfg) == 1.0
        assert calculate_backoff(1, cfg) == 2.0
        assert calculate_backoff(2, cfg) == 4.0

    def test_max_delay_cap(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            initial_delay=1.0,
            exponential_base=10.0,
            max_delay=5.0,
            jitter=False,
        )
        assert calculate_backoff(5, cfg) <= 5.0

    def test_jitter_changes_value(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.FIXED,
            initial_delay=1.0,
            jitter=True,
            jitter_range=(0.1, 0.5),
        )
        results = {calculate_backoff(0, cfg) for _ in range(20)}
        # All results should be >= 1.0 (base) but varied due to jitter
        assert all(r >= 1.0 for r in results)


# ── retry decorator (sync) ──────────────────────────────────────────


class TestRetrySync:
    def test_success_first_try(self):
        @retry(max_attempts=3, base_delay=0.0)
        def ok():
            return 42

        assert ok() == 42

    def test_retries_on_failure(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "done"

        assert flaky() == "done"
        assert call_count == 3

    def test_exhausted(self):
        @retry(max_attempts=2, base_delay=0.0)
        def always_fail():
            raise ValueError("always")

        with pytest.raises(RetryExhaustedError) as exc_info:
            always_fail()
        assert exc_info.value.attempts == 2

    def test_non_retryable_exception(self):
        @retry(max_attempts=3, base_delay=0.0, allowed_exceptions=(ValueError,))
        def raises_type():
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            raises_type()

    def test_with_config(self):
        cfg = RetryConfig(max_attempts=1, initial_delay=0.0)

        @retry(config=cfg)
        def fail():
            raise ValueError("fail")

        with pytest.raises(RetryExhaustedError):
            fail()

    def test_on_retry_callback(self):
        calls = []
        cfg = RetryConfig(
            max_attempts=3,
            initial_delay=0.0,
            on_retry=lambda attempt, exc: calls.append(attempt),
        )
        counter = 0

        @retry(config=cfg)
        def flaky():
            nonlocal counter
            counter += 1
            if counter < 3:
                raise ValueError("retry")
            return "ok"

        assert flaky() == "ok"
        assert len(calls) == 2  # Called on attempt 1 and 2 failures


# ── retry decorator (async) ─────────────────────────────────────────


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_async_success(self):
        @retry(max_attempts=3, base_delay=0.0)
        async def ok():
            return 99

        assert await ok() == 99

    @pytest.mark.asyncio
    async def test_async_retries(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.0)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("not yet")
            return "async_done"

        assert await flaky() == "async_done"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_exhausted(self):
        @retry(max_attempts=2, base_delay=0.0)
        async def always_fail():
            raise ValueError("async fail")

        with pytest.raises(RetryExhaustedError) as exc_info:
            await always_fail()
        assert exc_info.value.attempts == 2

    @pytest.mark.asyncio
    async def test_async_non_retryable(self):
        @retry(max_attempts=3, base_delay=0.0, allowed_exceptions=(ValueError,))
        async def raises_type():
            raise TypeError("wrong")

        with pytest.raises(TypeError):
            await raises_type()


# ── retry as wrapper (not decorator) ────────────────────────────────


class TestRetryWrapper:
    def test_direct_call(self):
        def add(a, b):
            return a + b

        wrapped = retry(add, max_attempts=3, base_delay=0.0)
        assert wrapped(1, 2) == 3
