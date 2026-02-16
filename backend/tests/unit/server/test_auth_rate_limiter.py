"""Tests for backend.server.middleware.auth_rate_limiter — in-memory rate limiting."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.server.middleware.auth_rate_limiter import (
    AuthRateLimiter,
    _auth_rate_limit_store,
)


@pytest.fixture(autouse=True)
def _clear_store():
    """Clear global rate limit store before each test."""
    _auth_rate_limit_store.clear()
    yield
    _auth_rate_limit_store.clear()


# ── Constructor & config ──────────────────────────────────────────────

class TestAuthRateLimiterInit:
    def test_defaults(self):
        limiter = AuthRateLimiter()
        assert limiter.login_attempts_per_15min == 5
        assert limiter.register_attempts_per_hour == 3
        assert limiter.password_reset_per_hour == 3
        assert limiter.enabled is True

    def test_custom_limits(self):
        limiter = AuthRateLimiter(
            login_attempts_per_15min=10,
            register_attempts_per_hour=5,
            password_reset_per_hour=2,
            enabled=False,
        )
        assert limiter.login_attempts_per_15min == 10
        assert limiter.enabled is False


# ── _get_endpoint_type ────────────────────────────────────────────────

class TestGetEndpointType:
    def test_login(self):
        limiter = AuthRateLimiter()
        assert limiter._get_endpoint_type("/api/auth/login") == "login"

    def test_register(self):
        limiter = AuthRateLimiter()
        assert limiter._get_endpoint_type("/api/auth/register") == "register"

    def test_signup(self):
        limiter = AuthRateLimiter()
        assert limiter._get_endpoint_type("/api/auth/signup") == "register"

    def test_password_reset(self):
        limiter = AuthRateLimiter()
        assert limiter._get_endpoint_type("/api/auth/password-reset") == "password_reset"

    def test_forgot_password(self):
        limiter = AuthRateLimiter()
        assert limiter._get_endpoint_type("/api/auth/forgot-password") == "password_reset"

    def test_other(self):
        limiter = AuthRateLimiter()
        assert limiter._get_endpoint_type("/api/auth/token") == "other"


# ── _get_rate_limit_key ──────────────────────────────────────────────

class TestGetRateLimitKey:
    def test_uses_forwarded_for(self):
        limiter = AuthRateLimiter()
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
        result = limiter._get_rate_limit_key(request)
        assert result == "auth:1.2.3.4"

    def test_uses_client_host(self):
        limiter = AuthRateLimiter()
        request = MagicMock()
        request.headers = {}
        request.client.host = "192.168.1.1"
        result = limiter._get_rate_limit_key(request)
        assert result == "auth:192.168.1.1"

    def test_no_client(self):
        limiter = AuthRateLimiter()
        request = MagicMock()
        request.headers = {}
        request.client = None
        result = limiter._get_rate_limit_key(request)
        assert result == "auth:unknown"


# ── _check_rate_limit ────────────────────────────────────────────────

class TestCheckRateLimit:
    @pytest.mark.asyncio
    async def test_login_within_limit(self):
        limiter = AuthRateLimiter(login_attempts_per_15min=3)
        assert await limiter._check_rate_limit("key", "login") is True

    @pytest.mark.asyncio
    async def test_login_exceeds_limit(self):
        limiter = AuthRateLimiter(login_attempts_per_15min=2)
        _auth_rate_limit_store["key"]["login_attempts"] = [
            time.time(), time.time()
        ]
        assert await limiter._check_rate_limit("key", "login") is False

    @pytest.mark.asyncio
    async def test_register_within_limit(self):
        limiter = AuthRateLimiter(register_attempts_per_hour=3)
        assert await limiter._check_rate_limit("key", "register") is True

    @pytest.mark.asyncio
    async def test_register_exceeds_limit(self):
        limiter = AuthRateLimiter(register_attempts_per_hour=1)
        _auth_rate_limit_store["key"]["register_attempts"] = [time.time()]
        assert await limiter._check_rate_limit("key", "register") is False

    @pytest.mark.asyncio
    async def test_password_reset_within_limit(self):
        limiter = AuthRateLimiter(password_reset_per_hour=3)
        assert await limiter._check_rate_limit("key", "password_reset") is True

    @pytest.mark.asyncio
    async def test_password_reset_exceeds_limit(self):
        limiter = AuthRateLimiter(password_reset_per_hour=1)
        _auth_rate_limit_store["key"]["password_reset_attempts"] = [time.time()]
        assert await limiter._check_rate_limit("key", "password_reset") is False

    @pytest.mark.asyncio
    async def test_old_attempts_cleaned(self):
        limiter = AuthRateLimiter(login_attempts_per_15min=2)
        old_time = time.time() - 1000  # Past the 900s window
        _auth_rate_limit_store["key"]["login_attempts"] = [old_time, old_time]
        assert await limiter._check_rate_limit("key", "login") is True

    @pytest.mark.asyncio
    async def test_other_type_uses_login_limit(self):
        limiter = AuthRateLimiter(login_attempts_per_15min=1)
        _auth_rate_limit_store["key"]["login_attempts"] = [time.time()]
        assert await limiter._check_rate_limit("key", "other") is False


# ── _record_attempt ───────────────────────────────────────────────────

class TestRecordAttempt:
    @pytest.mark.asyncio
    async def test_records_login_attempt(self):
        limiter = AuthRateLimiter()
        await limiter._record_attempt("key", "login")
        assert len(_auth_rate_limit_store["key"]["login_attempts"]) == 1

    @pytest.mark.asyncio
    async def test_records_register_attempt(self):
        limiter = AuthRateLimiter()
        await limiter._record_attempt("key", "register")
        assert len(_auth_rate_limit_store["key"]["register_attempts"]) == 1

    @pytest.mark.asyncio
    async def test_records_password_reset_attempt(self):
        limiter = AuthRateLimiter()
        await limiter._record_attempt("key", "password_reset")
        assert len(_auth_rate_limit_store["key"]["password_reset_attempts"]) == 1


# ── _record_failed_attempt ────────────────────────────────────────────

class TestRecordFailedAttempt:
    @pytest.mark.asyncio
    async def test_records_failed(self):
        limiter = AuthRateLimiter()
        await limiter._record_failed_attempt("key", "login")
        assert len(_auth_rate_limit_store["key"]["failed_attempts"]) == 1

    @pytest.mark.asyncio
    async def test_cleans_old_failed_attempts(self):
        limiter = AuthRateLimiter()
        old_time = time.time() - 7200  # 2 hours ago
        _auth_rate_limit_store["key"]["failed_attempts"] = [old_time]
        await limiter._record_failed_attempt("key", "login")
        # Old one should be cleaned, only new one remains
        assert len(_auth_rate_limit_store["key"]["failed_attempts"]) == 1


# ── _get_retry_after ──────────────────────────────────────────────────

class TestGetRetryAfter:
    def test_few_failures(self):
        limiter = AuthRateLimiter()
        _auth_rate_limit_store["key"]["failed_attempts"] = [time.time()]
        assert limiter._get_retry_after("key", "login") == 60

    def test_moderate_failures(self):
        limiter = AuthRateLimiter()
        _auth_rate_limit_store["key"]["failed_attempts"] = [
            time.time() for _ in range(4)
        ]
        assert limiter._get_retry_after("key", "login") == 300

    def test_many_failures(self):
        limiter = AuthRateLimiter()
        _auth_rate_limit_store["key"]["failed_attempts"] = [
            time.time() for _ in range(7)
        ]
        assert limiter._get_retry_after("key", "login") == 900

    def test_extreme_failures(self):
        limiter = AuthRateLimiter()
        _auth_rate_limit_store["key"]["failed_attempts"] = [
            time.time() for _ in range(15)
        ]
        assert limiter._get_retry_after("key", "login") == 3600


# ── __call__ middleware ───────────────────────────────────────────────

class TestAuthRateLimiterMiddleware:
    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        limiter = AuthRateLimiter(enabled=False)
        request = MagicMock()
        response = MagicMock()
        call_next = AsyncMock(return_value=response)
        result = await limiter(request, call_next)
        assert result is response

    @pytest.mark.asyncio
    async def test_non_auth_path_passes_through(self):
        limiter = AuthRateLimiter()
        request = MagicMock()
        request.url.path = "/api/settings"
        response = MagicMock()
        call_next = AsyncMock(return_value=response)
        result = await limiter(request, call_next)
        assert result is response

    @pytest.mark.asyncio
    async def test_auth_path_within_limit(self):
        limiter = AuthRateLimiter(login_attempts_per_15min=10)
        request = MagicMock()
        request.url.path = "/api/auth/login"
        request.headers = {}
        request.client.host = "1.1.1.1"
        response = MagicMock()
        response.status_code = 200
        call_next = AsyncMock(return_value=response)
        result = await limiter(request, call_next)
        assert result is response

    @pytest.mark.asyncio
    async def test_auth_path_exceeds_limit_returns_429(self):
        limiter = AuthRateLimiter(login_attempts_per_15min=1)
        request = MagicMock()
        request.url.path = "/api/auth/login"
        request.headers = {}
        request.client.host = "2.2.2.2"
        # Fill the rate limit
        _auth_rate_limit_store["auth:2.2.2.2"]["login_attempts"] = [time.time()]
        call_next = AsyncMock()
        result = await limiter(request, call_next)
        assert result.status_code == 429
        call_next.assert_not_called()
