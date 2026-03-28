"""Tests for backend.gateway.middleware.redis_cost_quota — RedisCostQuotaMiddleware."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.gateway.middleware.redis_cost_quota import RedisCostQuotaMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def middleware():
    """RedisCostQuotaMiddleware with Redis disabled (fallback mode)."""
    with patch("backend.gateway.middleware.redis_cost_quota.REDIS_AVAILABLE", False):
        mw = RedisCostQuotaMiddleware(enabled=True, fallback_enabled=True)
        yield mw


@pytest.fixture
def redis_middleware():
    """RedisCostQuotaMiddleware with a mocked Redis client."""
    with patch("backend.gateway.middleware.redis_cost_quota.REDIS_AVAILABLE", True):
        mw = RedisCostQuotaMiddleware.__new__(RedisCostQuotaMiddleware)
        # Initialize parent state
        mw.enabled = True
        mw.fallback_enabled = True
        mw.redis_url = "redis://localhost:6379"
        mw.connection_pool_size = 5
        mw.connection_timeout = 2.0
        mw._redis_client = AsyncMock()
        mw._redis_pool = MagicMock()
        mw._redis_health_check_interval = 60.0
        mw._last_health_check = time.time()
        mw._redis_healthy = True
        # Parent class attributes
        from backend.gateway.middleware.cost_quota import QuotaConfig

        mw.config = QuotaConfig(
            daily_limit=100.0, monthly_limit=1000.0, burst_limit=10.0
        )
        mw.day_window = 86400
        mw.month_window = 86400 * 30
        yield mw


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------
class TestRedisKeys:
    def test_key_structure(self):
        keys = RedisCostQuotaMiddleware._redis_keys("user:123")
        assert "daily" in keys.daily
        assert "monthly" in keys.monthly
        assert "user:123" in keys.daily
        assert "user:123" in keys.monthly_reset


class TestRedisClientSupportsMutation:
    def test_supports(self):
        client = MagicMock()
        client.set = MagicMock()
        client.expire = MagicMock()
        assert RedisCostQuotaMiddleware._redis_client_supports_mutation(client) is True

    def test_missing_set(self):
        client = MagicMock(spec=[])
        assert RedisCostQuotaMiddleware._redis_client_supports_mutation(client) is False


# ---------------------------------------------------------------------------
# _is_redis_enabled
# ---------------------------------------------------------------------------
class TestIsRedisEnabled:
    def test_disabled(self, middleware):
        with patch("backend.gateway.middleware.redis_cost_quota.REDIS_AVAILABLE", False):
            middleware.fallback_enabled = False
            assert middleware._is_redis_enabled() is False

    def test_enabled(self, redis_middleware):
        with patch("backend.gateway.middleware.redis_cost_quota.REDIS_AVAILABLE", True):
            assert redis_middleware._is_redis_enabled() is True


# ---------------------------------------------------------------------------
# _apply_limit_checks
# ---------------------------------------------------------------------------
class TestApplyLimitChecks:
    def test_within_limits(self, redis_middleware):
        result = redis_middleware._apply_limit_checks(
            "user:1", redis_middleware.config, 1.0, 5.0
        )
        assert result is True

    def test_daily_exceeded(self, redis_middleware):
        result = redis_middleware._apply_limit_checks(
            "user:1",
            redis_middleware.config,
            redis_middleware.config.daily_limit + 1,
            0.0,
        )
        assert result is False

    def test_monthly_exceeded(self, redis_middleware):
        result = redis_middleware._apply_limit_checks(
            "user:1",
            redis_middleware.config,
            0.0,
            redis_middleware.config.monthly_limit + 1,
        )
        assert result is False


# ---------------------------------------------------------------------------
# record_cost (sync — uses parent in-memory)
# ---------------------------------------------------------------------------
class TestRecordCostSync:
    def test_disabled_noop(self, middleware):
        middleware.enabled = False
        middleware.record_cost("user:1", 1.0)  # Should not raise

    def test_records(self, middleware):
        middleware.record_cost("user:1", 0.5)
        # Just check no error — parent stores in-memory


# ---------------------------------------------------------------------------
# Async methods with mocked Redis
# ---------------------------------------------------------------------------
class TestCheckQuota:
    @pytest.mark.asyncio
    async def test_check_quota_fallback(self, middleware):
        # No Redis available → in-memory check
        result = await middleware._check_quota("user:1")
        assert result is True  # Default: within limits

    @pytest.mark.asyncio
    async def test_check_quota_redis(self, redis_middleware):
        redis_middleware._redis_client.get = AsyncMock(return_value="0.0")
        redis_middleware._redis_client.set = AsyncMock()
        redis_middleware._redis_client.expire = AsyncMock()
        result = await redis_middleware._check_quota("user:1")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_quota_redis_error_fallback(self, redis_middleware):
        redis_middleware._redis_client.get = AsyncMock(
            side_effect=Exception("conn lost")
        )
        result = await redis_middleware._check_quota("user:1")
        assert result is True  # fallback allows


class TestGetRemainingQuota:
    @pytest.mark.asyncio
    async def test_fallback(self, middleware):
        result = await middleware._get_remaining_quota("user:1")
        assert "daily" in result
        assert "monthly" in result

    @pytest.mark.asyncio
    async def test_redis(self, redis_middleware):
        redis_middleware._redis_client.get = AsyncMock(return_value="1.0")
        redis_middleware._redis_client.set = AsyncMock()
        redis_middleware._redis_client.expire = AsyncMock()
        result = await redis_middleware._get_remaining_quota("user:1")
        assert result["daily"] >= 0
        assert result["monthly"] >= 0


class TestRecordCostAsync:
    @pytest.mark.asyncio
    async def test_disabled(self, middleware):
        middleware.enabled = False
        await middleware.record_cost_async("user:1", 1.0)

    @pytest.mark.asyncio
    async def test_no_redis_fallback(self, middleware):
        await middleware.record_cost_async("user:1", 0.5)

    @pytest.mark.asyncio
    async def test_redis_success(self, redis_middleware):
        redis_middleware._redis_client.get = AsyncMock(return_value="100.0")
        redis_middleware._redis_client.set = AsyncMock()
        redis_middleware._redis_client.expire = AsyncMock()
        redis_middleware._redis_client.incrbyfloat = AsyncMock()
        await redis_middleware.record_cost_async("user:1", 0.25)
        assert redis_middleware._redis_client.incrbyfloat.call_count >= 2

    @pytest.mark.asyncio
    async def test_redis_error_fallback(self, redis_middleware):
        redis_middleware._redis_client.get = AsyncMock(side_effect=Exception("fail"))
        # Should not raise
        await redis_middleware.record_cost_async("user:1", 0.1)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_success(self, redis_middleware):
        redis_middleware._last_health_check = 0  # Force check
        redis_middleware._redis_client.ping = AsyncMock()
        await redis_middleware._health_check_existing_client(time.time())
        assert redis_middleware._redis_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, redis_middleware):
        redis_middleware._last_health_check = 0  # Force check
        redis_middleware._redis_client.ping = AsyncMock(
            side_effect=Exception("disconnected")
        )
        await redis_middleware._health_check_existing_client(time.time())
        assert redis_middleware._redis_healthy is False
        assert redis_middleware._redis_client is None

    @pytest.mark.asyncio
    async def test_health_check_skipped(self, redis_middleware):
        """Recent health check → skip."""
        redis_middleware._last_health_check = time.time()
        redis_middleware._redis_client.ping = AsyncMock()
        await redis_middleware._health_check_existing_client(time.time())
        redis_middleware._redis_client.ping.assert_not_called()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
class TestObservability:
    def test_should_instrument_disabled(self, redis_middleware):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}, clear=False):
            os.environ.pop("OTEL_INSTRUMENT_REDIS", None)
            assert redis_middleware._should_instrument_redis() is False

    def test_should_instrument_enabled(self, redis_middleware):
        with patch.dict(
            os.environ,
            {"OTEL_INSTRUMENT_REDIS": "true", "OTEL_SAMPLE_REDIS": "1.0"},
        ):
            assert redis_middleware._should_instrument_redis() is True


# ---------------------------------------------------------------------------
# _handle_redis_check_failure
# ---------------------------------------------------------------------------
class TestHandleRedisCheckFailure:
    @pytest.mark.asyncio
    async def test_fallback_enabled(self, redis_middleware):
        result = await redis_middleware._handle_redis_check_failure(
            Exception("fail"), "user:1"
        )
        assert result is True  # fail-open

    @pytest.mark.asyncio
    async def test_fallback_disabled(self, redis_middleware):
        redis_middleware.fallback_enabled = False
        result = await redis_middleware._handle_redis_check_failure(
            Exception("fail"), "user:1"
        )
        assert result is False  # fail-closed
