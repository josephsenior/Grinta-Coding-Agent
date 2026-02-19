"""Unit tests for backend.utils.retry — backoff calculation & retry decorator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core.enums import RetryStrategy
from backend.core.schemas import RetryConfig
from backend.utils.retry import (
    RetryError,
    RetryExhaustedError,
    calculate_backoff,
    retry,
)


# ---------------------------------------------------------------------------
# calculate_backoff
# ---------------------------------------------------------------------------


class TestCalculateBackoff:
    def test_immediate_zero(self):
        cfg = RetryConfig(strategy=RetryStrategy.IMMEDIATE, jitter=False)
        assert calculate_backoff(0, cfg) == 0.0
        assert calculate_backoff(5, cfg) == 0.0

    def test_fixed(self):
        cfg = RetryConfig(strategy=RetryStrategy.FIXED, initial_delay=2.0, jitter=False)
        assert calculate_backoff(0, cfg) == 2.0
        assert calculate_backoff(3, cfg) == 2.0

    def test_linear(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.LINEAR, initial_delay=1.0, jitter=False
        )
        assert calculate_backoff(0, cfg) == 1.0
        assert calculate_backoff(1, cfg) == 2.0
        assert calculate_backoff(4, cfg) == 5.0

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
        assert calculate_backoff(3, cfg) == 8.0

    def test_max_delay_cap(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            initial_delay=1.0,
            exponential_base=2.0,
            max_delay=5.0,
            jitter=False,
        )
        assert calculate_backoff(10, cfg) == 5.0

    def test_jitter_adds_randomness(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.FIXED,
            initial_delay=1.0,
            jitter=True,
            jitter_range=(0.0, 0.5),
        )
        delays = {calculate_backoff(0, cfg) for _ in range(50)}
        # With jitter, values should vary (not all identical)
        assert len(delays) > 1

    def test_jitter_bounded(self):
        cfg = RetryConfig(
            strategy=RetryStrategy.FIXED,
            initial_delay=1.0,
            jitter=True,
            jitter_range=(0.0, 0.5),
        )
        for _ in range(100):
            d = calculate_backoff(0, cfg)
            assert 1.0 <= d <= 1.5


# ---------------------------------------------------------------------------
# RetryError hierarchy
# ---------------------------------------------------------------------------


class TestRetryErrors:
    def test_retry_error(self):
        with pytest.raises(RetryError):
            raise RetryError("boom")

    def test_exhausted_error(self):
        err = RetryExhaustedError(3, ValueError("fail"))
        assert err.attempts == 3
        assert isinstance(err.last_exception, ValueError)
        assert "3 attempts" in str(err)

    def test_exhausted_is_retry_error(self):
        assert issubclass(RetryExhaustedError, RetryError)


# ---------------------------------------------------------------------------
# retry decorator — sync
# ---------------------------------------------------------------------------


class TestRetrySyncDecorator:
    def test_success_first_attempt(self):
        call_count = 0

        @retry(max_attempts=3)
        def good():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert good() == "ok"
        assert call_count == 1

    def test_retries_then_succeeds(self):
        attempt = 0

        @retry(
            config=RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
            )
        )
        def flaky():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise ValueError("not yet")
            return "done"

        assert flaky() == "done"
        assert attempt == 3

    def test_exhausts_raises(self):
        @retry(
            config=RetryConfig(
                max_attempts=2,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
            )
        )
        def always_fail():
            raise ValueError("boom")

        with pytest.raises(RetryExhaustedError) as exc_info:
            always_fail()
        assert exc_info.value.attempts == 2

    def test_non_retryable_propagates(self):
        @retry(
            config=RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
                retryable_exceptions=(ValueError,),
            )
        )
        def raise_type_error():
            raise TypeError("wrong")

        with pytest.raises(TypeError, match="wrong"):
            raise_type_error()

    def test_on_retry_callback(self):
        callback = MagicMock()

        @retry(
            config=RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
                on_retry=callback,
            )
        )
        def fail_once():
            if callback.call_count == 0:
                raise ValueError("first fail")
            return "ok"

        # The callback is called with (attempt_number, exception)
        fail_once()
        assert callback.call_count >= 1


# ---------------------------------------------------------------------------
# retry decorator — async
# ---------------------------------------------------------------------------


class TestRetryAsyncDecorator:
    @pytest.mark.asyncio
    async def test_async_success(self):
        @retry(
            config=RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
            )
        )
        async def async_good():
            return "async ok"

        assert await async_good() == "async ok"

    @pytest.mark.asyncio
    async def test_async_retries(self):
        attempt = 0

        @retry(
            config=RetryConfig(
                max_attempts=3,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
            )
        )
        async def async_flaky():
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise ValueError("not yet")
            return "done"

        assert await async_flaky() == "done"
        assert attempt == 2

    @pytest.mark.asyncio
    async def test_async_exhausted(self):
        @retry(
            config=RetryConfig(
                max_attempts=2,
                initial_delay=0.0,
                strategy=RetryStrategy.IMMEDIATE,
            )
        )
        async def always_fail():
            raise ValueError("fail")

        with pytest.raises(RetryExhaustedError):
            await always_fail()
