"""Tests for backend.server.middleware.rate_limiter — RateLimiter, EndpointRateLimiter, _purge_expired_keys."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.server.middleware.rate_limiter import (
    EndpointRateLimiter,
    RateLimiter,
    _purge_expired_keys,
    _rate_limit_store,
)


# ── Cleanup ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_store():
    """Clean up module-level store between tests."""
    _rate_limit_store.clear()
    yield
    _rate_limit_store.clear()


# ── RateLimiter init ─────────────────────────────────────────────────


class TestRateLimiterInit:
    def test_defaults(self):
        rl = RateLimiter()
        assert rl.requests_per_hour == 100
        assert rl.burst_limit == 20
        assert rl.enabled is True

    def test_custom_values(self):
        rl = RateLimiter(requests_per_hour=500, burst_limit=50, enabled=False)
        assert rl.requests_per_hour == 500
        assert rl.burst_limit == 50
        assert rl.enabled is False


# ── _check_rate_limit ────────────────────────────────────────────────


class TestCheckRateLimit:
    @pytest.mark.asyncio
    async def test_allows_first_request(self):
        rl = RateLimiter(requests_per_hour=100, burst_limit=20)
        assert await rl._check_rate_limit("test-key") is True

    @pytest.mark.asyncio
    async def test_denies_after_hourly_limit(self):
        rl = RateLimiter(requests_per_hour=5, burst_limit=100)
        for _ in range(5):
            await rl._check_rate_limit("hourly-key")
        assert await rl._check_rate_limit("hourly-key") is False

    @pytest.mark.asyncio
    async def test_denies_after_burst_limit(self):
        rl = RateLimiter(requests_per_hour=1000, burst_limit=3)
        for _ in range(3):
            await rl._check_rate_limit("burst-key")
        assert await rl._check_rate_limit("burst-key") is False

    @pytest.mark.asyncio
    async def test_cleans_old_timestamps(self):
        rl = RateLimiter(requests_per_hour=5, burst_limit=100)
        # Add old timestamps
        old_time = time.time() - 7200  # 2 hours ago
        _rate_limit_store["old-key"] = [old_time] * 5
        # Should allow because old timestamps are expired
        assert await rl._check_rate_limit("old-key") is True

    @pytest.mark.asyncio
    async def test_separate_keys(self):
        rl = RateLimiter(requests_per_hour=2, burst_limit=100)
        await rl._check_rate_limit("key-a")
        await rl._check_rate_limit("key-a")
        # key-a exhausted
        assert await rl._check_rate_limit("key-a") is False
        # key-b should still work
        assert await rl._check_rate_limit("key-b") is True


# ── _get_remaining_requests ──────────────────────────────────────────


class TestGetRemainingRequests:
    @pytest.mark.asyncio
    async def test_full_remaining(self):
        rl = RateLimiter(requests_per_hour=100)
        remaining = await rl._get_remaining_requests("fresh-key")
        assert remaining == 100

    @pytest.mark.asyncio
    async def test_decreases_after_requests(self):
        rl = RateLimiter(requests_per_hour=10, burst_limit=100)
        for _ in range(3):
            await rl._check_rate_limit("decrement-key")
        remaining = await rl._get_remaining_requests("decrement-key")
        assert remaining == 7

    @pytest.mark.asyncio
    async def test_zero_remaining(self):
        rl = RateLimiter(requests_per_hour=2, burst_limit=100)
        for _ in range(5):
            await rl._check_rate_limit("zero-key")
        remaining = await rl._get_remaining_requests("zero-key")
        assert remaining == 0


# ── _get_rate_limit_key ──────────────────────────────────────────────


class TestGetRateLimitKey:
    @pytest.mark.asyncio
    async def test_uses_user_id(self):
        rl = RateLimiter()
        req = MagicMock()
        req.state.user_id = "user-42"
        key = await rl._get_rate_limit_key(req)
        assert key == "user:user-42"

    @pytest.mark.asyncio
    async def test_falls_back_to_ip(self):
        rl = RateLimiter()
        req = MagicMock()
        req.state.user_id = None
        req.client.host = "10.0.0.1"
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(return_value=None)
        req.headers = headers_mock
        key = await rl._get_rate_limit_key(req)
        assert key.startswith("ip:")

    @pytest.mark.asyncio
    async def test_uses_forwarded_for(self):
        rl = RateLimiter()
        req = MagicMock()
        req.state.user_id = None
        req.client.host = "192.168.1.1"
        headers = {"X-Forwarded-For": "10.0.0.1, 192.168.1.1"}
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(side_effect=lambda k, d=None: headers.get(k, d))
        req.headers = headers_mock
        key = await rl._get_rate_limit_key(req)
        assert key.startswith("ip:")


# ── RateLimiter.__call__ ─────────────────────────────────────────────


class TestRateLimiterCall:
    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        rl = RateLimiter(enabled=False)
        req = MagicMock()
        resp = MagicMock()
        call_next = AsyncMock(return_value=resp)
        result = await rl(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_health_check_skips(self):
        rl = RateLimiter(requests_per_hour=1, burst_limit=1)
        req = MagicMock()
        req.url.path = "/health"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)
        result = await rl(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_assets_skip(self):
        rl = RateLimiter(requests_per_hour=1, burst_limit=1)
        req = MagicMock()
        req.url.path = "/assets/main.js"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)
        result = await rl(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_adds_rate_limit_headers(self):
        rl = RateLimiter(requests_per_hour=100, burst_limit=50)
        req = MagicMock()
        req.url.path = "/api/conversations"
        req.state.user_id = "test-user"
        req.client.host = "127.0.0.1"
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(return_value=None)
        req.headers = headers_mock
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        await rl(req, call_next)
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers


# ── _purge_expired_keys ──────────────────────────────────────────────


class TestPurgeExpiredKeys:
    def test_removes_stale_keys(self):
        import backend.server.middleware.rate_limiter as mod

        old_cleanup = mod._last_cleanup
        mod._last_cleanup = 0.0  # Force cleanup

        old_time = time.time() - 7200
        _rate_limit_store["stale-key"] = [old_time]
        _rate_limit_store["fresh-key"] = [time.time()]

        _purge_expired_keys(max_age=3600.0)

        assert "stale-key" not in _rate_limit_store
        assert "fresh-key" in _rate_limit_store

        mod._last_cleanup = old_cleanup

    def test_skips_if_recently_cleaned(self):
        import backend.server.middleware.rate_limiter as mod

        mod._last_cleanup = time.time()  # Just cleaned

        old_time = time.time() - 7200
        _rate_limit_store["should-stay"] = [old_time]

        _purge_expired_keys(max_age=3600.0)

        # Should NOT be purged because cleanup was recent
        assert "should-stay" in _rate_limit_store


# ── EndpointRateLimiter ──────────────────────────────────────────────


class TestEndpointRateLimiter:
    def test_get_limits_for_known_path(self):
        erl = EndpointRateLimiter(enabled=True)
        limits = erl._get_limits_for_path("/api/conversations/abc")
        assert isinstance(limits, tuple)
        assert len(limits) == 2

    def test_get_limits_for_unknown_path(self):
        erl = EndpointRateLimiter(enabled=True)
        limits = erl._get_limits_for_path("/api/unknown/path")
        assert limits == erl.LIMITS["default"]

    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        erl = EndpointRateLimiter(enabled=False)
        req = MagicMock()
        resp = MagicMock()
        call_next = AsyncMock(return_value=resp)
        result = await erl(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_options_skip(self):
        erl = EndpointRateLimiter(enabled=True)
        req = MagicMock()
        req.url.path = "/api/options/languages"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)
        result = await erl(req, call_next)
        assert result is resp
