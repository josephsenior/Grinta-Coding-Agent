"""Comprehensive tests for server middleware_core components.

Tests CORS, cache control, and rate limiting middleware.
"""

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.testclient import TestClient

from backend.api.middleware_core import (
    CacheControlMiddleware,
    InMemoryRateLimiter,
    LocalhostCORSMiddleware,
    RateLimitMiddleware,
)


class TestLocalhostCORSMiddleware(unittest.TestCase):
    """Tests for LocalhostCORSMiddleware - localhost whitelisting CORS."""

    def test_init_without_env_var(self) -> None:
        """Test initialization without PERMITTED_CORS_ORIGINS env var."""
        app = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            middleware = LocalhostCORSMiddleware(app)

        self.assertIsNotNone(middleware)
        # allow_origins should be empty tuple
        self.assertEqual(middleware.allow_origins, ())

    def test_init_with_env_var(self) -> None:
        """Test initialization with PERMITTED_CORS_ORIGINS set."""
        app = MagicMock()

        with patch.dict(
            "os.environ",
            {"PERMITTED_CORS_ORIGINS": "https://example.com, https://app.example.com"},
        ):
            middleware = LocalhostCORSMiddleware(app)

        self.assertEqual(
            middleware.allow_origins,
            ("https://example.com", "https://app.example.com"),
        )

    def test_is_allowed_origin_localhost(self) -> None:
        """Test localhost is always allowed."""
        app = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            middleware = LocalhostCORSMiddleware(app)

        self.assertTrue(middleware.is_allowed_origin("http://localhost:3000"))
        self.assertTrue(middleware.is_allowed_origin("http://localhost"))
        self.assertTrue(middleware.is_allowed_origin("https://localhost:8080"))

    def test_is_allowed_origin_127001(self) -> None:
        """Test 127.0.0.1 is always allowed."""
        app = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            middleware = LocalhostCORSMiddleware(app)

        self.assertTrue(middleware.is_allowed_origin("http://127.0.0.1:3000"))
        self.assertTrue(middleware.is_allowed_origin("http://127.0.0.1"))
        self.assertTrue(middleware.is_allowed_origin("https://127.0.0.1:8443"))

    def test_is_allowed_origin_configured(self) -> None:
        """Test configured origins are allowed."""
        app = MagicMock()
        with patch.dict(
            "os.environ", {"PERMITTED_CORS_ORIGINS": "https://example.com"}
        ):
            middleware = LocalhostCORSMiddleware(app)

        self.assertTrue(middleware.is_allowed_origin("https://example.com"))

    def test_is_allowed_origin_unconfigured(self) -> None:
        """Test unconfigured origins are rejected."""
        app = MagicMock()
        with patch.dict(
            "os.environ", {"PERMITTED_CORS_ORIGINS": "https://example.com"}
        ):
            middleware = LocalhostCORSMiddleware(app)

        self.assertFalse(middleware.is_allowed_origin("https://malicious.com"))

    def test_is_allowed_origin_empty(self) -> None:
        """Test empty origin returns False."""
        app = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            middleware = LocalhostCORSMiddleware(app)

        self.assertFalse(middleware.is_allowed_origin(""))

    def test_allows_credentials_enabled(self) -> None:
        """Test allow_credentials is configured (reflected in preflight headers)."""
        app = FastAPI()
        app.add_middleware(LocalhostCORSMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "OK"}

        with TestClient(app) as client:
            response = client.options(
                "/test",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                },
            )
            self.assertEqual(
                response.headers.get("access-control-allow-credentials"), "true"
            )

    def test_allows_all_methods_and_headers(self) -> None:
        """Test all methods and headers are allowed."""
        app = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            middleware = LocalhostCORSMiddleware(app)

        # Starlette expands ["*"] into explicit HTTP method tuple
        self.assertIn("GET", middleware.allow_methods)
        self.assertIn("POST", middleware.allow_methods)
        self.assertIn("DELETE", middleware.allow_methods)
        # Headers: Starlette stores allow_all_headers flag when ["*"] is passed
        self.assertTrue(middleware.allow_all_headers)


class TestCacheControlMiddleware(unittest.IsolatedAsyncioTestCase):
    """Tests for CacheControlMiddleware - cache header management."""

    async def test_assets_route_cacheable(self) -> None:
        """Test /assets routes get long cache headers."""
        app = MagicMock()
        middleware = CacheControlMiddleware(app)

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/assets/styles.css"

        mock_response = Response(content=b"CSS content", media_type="text/css")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, call_next)

        self.assertIn("Cache-Control", response.headers)
        self.assertEqual(
            response.headers["Cache-Control"], "public, max-age=2592000, immutable"
        )

    async def test_non_assets_route_no_cache(self) -> None:
        """Test non-assets routes get no-cache headers."""
        app = MagicMock()
        middleware = CacheControlMiddleware(app)

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/api/conversations"

        mock_response = Response(content=b"API response")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, call_next)

        self.assertEqual(
            response.headers["Cache-Control"],
            "no-cache, no-store, must-revalidate, max-age=0",
        )
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["Expires"], "0")

    async def test_root_path_no_cache(self) -> None:
        """Test root path gets no-cache headers."""
        app = MagicMock()
        middleware = CacheControlMiddleware(app)

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/"

        mock_response = Response(content=b"Home page")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, call_next)

        self.assertIn("no-cache", response.headers["Cache-Control"])


class TestInMemoryRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Tests for InMemoryRateLimiter - request rate limiting logic."""

    def test_init_default_params(self) -> None:
        """Test rate limiter initializes with default parameters."""
        limiter = InMemoryRateLimiter()

        self.assertEqual(limiter.requests, 2)
        self.assertEqual(limiter.seconds, 1)
        self.assertEqual(limiter.sleep_seconds, 1)
        self.assertEqual(len(limiter.history), 0)

    def test_init_custom_params(self) -> None:
        """Test rate limiter initializes with custom parameters."""
        limiter = InMemoryRateLimiter(requests=10, seconds=60, sleep_seconds=5)

        self.assertEqual(limiter.requests, 10)
        self.assertEqual(limiter.seconds, 60)
        self.assertEqual(limiter.sleep_seconds, 5)

    def test_clean_old_requests_removes_expired(self) -> None:
        """Test _clean_old_requests removes timestamps outside window."""
        limiter = InMemoryRateLimiter(requests=5, seconds=10)

        now = datetime.now()
        old = now - timedelta(seconds=15)
        recent = now - timedelta(seconds=5)

        limiter.history["client1"] = [old, recent, now]
        limiter._clean_old_requests("client1")

        # Old timestamp should be removed
        self.assertEqual(len(limiter.history["client1"]), 2)
        self.assertNotIn(old, limiter.history["client1"])

    async def test_allows_requests_under_limit(self) -> None:
        """Test requests under limit are allowed."""
        limiter = InMemoryRateLimiter(requests=5, seconds=10)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")

        result = await limiter(mock_request)

        self.assertTrue(result)

    async def test_sleeps_when_over_limit(self) -> None:
        """Test limiter sleeps when over limit but under 2x."""
        limiter = InMemoryRateLimiter(requests=2, seconds=10, sleep_seconds=0.1)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")

        # Make 3 requests (over limit of 2)
        await limiter(mock_request)
        await limiter(mock_request)

        with patch("backend.api.middleware_core.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await limiter(mock_request)

        self.assertTrue(result)
        mock_sleep.assert_awaited_once_with(0.1)

    async def test_rejects_when_over_double_limit(self) -> None:
        """Test requests over 2x limit are rejected."""
        limiter = InMemoryRateLimiter(requests=2, seconds=10, sleep_seconds=1)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")

        # Make 5 requests (over 2x limit)
        for _ in range(5):
            await limiter(mock_request)

        # 6th request should be rejected
        result = await limiter(mock_request)

        self.assertFalse(result)

    async def test_rejects_immediately_when_sleep_zero(self) -> None:
        """Test limiter rejects immediately when sleep_seconds=0."""
        limiter = InMemoryRateLimiter(requests=2, seconds=10, sleep_seconds=0)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")

        # Make 3 requests (over limit)
        await limiter(mock_request)
        await limiter(mock_request)

        result = await limiter(mock_request)

        self.assertFalse(result)

    async def test_handles_missing_client(self) -> None:
        """Test limiter handles requests without client info."""
        limiter = InMemoryRateLimiter(requests=5, seconds=10)

        mock_request = MagicMock(spec=Request)
        mock_request.client = None

        result = await limiter(mock_request)

        self.assertTrue(result)
        self.assertIn("unknown", limiter.history)

    async def test_separate_clients_independent_limits(self) -> None:
        """Test different clients have independent rate limits."""
        limiter = InMemoryRateLimiter(requests=2, seconds=10)

        request1 = MagicMock(spec=Request)
        request1.client = MagicMock(host="192.168.1.100")

        request2 = MagicMock(spec=Request)
        request2.client = MagicMock(host="192.168.1.200")

        # Client 1 makes 2 requests
        await limiter(request1)
        await limiter(request1)

        # Client 2 should still be allowed
        result = await limiter(request2)
        self.assertTrue(result)

    async def test_handles_cancelled_error_during_sleep(self) -> None:
        """Test limiter re-raises CancelledError for graceful shutdown."""
        limiter = InMemoryRateLimiter(requests=1, seconds=10, sleep_seconds=10)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")

        # Make 2 requests to trigger sleep
        await limiter(mock_request)

        # Cancel during sleep
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await limiter(mock_request)


class TestRateLimitMiddleware(unittest.IsolatedAsyncioTestCase):
    """Tests for RateLimitMiddleware - FastAPI middleware wrapper."""

    async def test_init_with_rate_limiter(self) -> None:
        """Test middleware initializes with rate limiter instance."""
        app = MagicMock()
        limiter = InMemoryRateLimiter(requests=5, seconds=10)

        middleware = RateLimitMiddleware(app, limiter)

        self.assertEqual(middleware.rate_limiter, limiter)

    async def test_allows_request_under_limit(self) -> None:
        """Test requests under rate limit are allowed through."""
        app = MagicMock()
        limiter = InMemoryRateLimiter(requests=10, seconds=60)
        middleware = RateLimitMiddleware(app, limiter)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")
        mock_request.url.path = "/api/test"

        mock_response = Response(content=b"OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, call_next)

        self.assertEqual(response, mock_response)
        call_next.assert_called_once_with(mock_request)

    async def test_rejects_request_over_limit(self) -> None:
        """Test requests over rate limit return 429."""
        app = MagicMock()
        limiter = InMemoryRateLimiter(requests=1, seconds=10, sleep_seconds=0)
        middleware = RateLimitMiddleware(app, limiter)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")
        mock_request.url.path = "/api/test"

        call_next = AsyncMock()

        # Make 2 requests (over limit of 1)
        await middleware.dispatch(mock_request, call_next)
        response = await middleware.dispatch(mock_request, call_next)

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)

    async def test_assets_route_bypasses_rate_limit(self) -> None:
        """Test /assets routes bypass rate limiting."""
        app = MagicMock()
        limiter = InMemoryRateLimiter(requests=0, seconds=1, sleep_seconds=0)
        middleware = RateLimitMiddleware(app, limiter)

        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock(host="192.168.1.100")
        mock_request.url.path = "/assets/logo.png"

        mock_response = Response(content=b"Image data")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, call_next)

        # Should bypass rate limiter even with 0 requests allowed
        self.assertEqual(response, mock_response)

    def test_is_rate_limited_request_assets_false(self) -> None:
        """Test is_rate_limited_request returns False for /assets."""
        app = MagicMock()
        limiter = InMemoryRateLimiter()
        middleware = RateLimitMiddleware(app, limiter)

        mock_request = MagicMock()
        mock_request.url.path = "/assets/script.js"

        self.assertFalse(middleware.is_rate_limited_request(mock_request))

    def test_is_rate_limited_request_api_true(self) -> None:
        """Test is_rate_limited_request returns True for API routes."""
        app = MagicMock()
        limiter = InMemoryRateLimiter()
        middleware = RateLimitMiddleware(app, limiter)

        mock_request = MagicMock()
        mock_request.url.path = "/api/conversations"

        self.assertTrue(middleware.is_rate_limited_request(mock_request))


class TestMiddlewareIntegration(unittest.TestCase):
    """Integration tests for middleware with FastAPI."""

    def test_localhost_cors_integration(self) -> None:
        """Test LocalhostCORSMiddleware in FastAPI app."""
        app = FastAPI()
        app.add_middleware(LocalhostCORSMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "OK"}

        with TestClient(app) as client:
            response = client.get("/test", headers={"Origin": "http://localhost:3000"})
            # CORS headers should be present
            self.assertEqual(response.status_code, 200)

    def test_cache_control_integration(self) -> None:
        """Test CacheControlMiddleware in FastAPI app."""
        app = FastAPI()
        app.add_middleware(CacheControlMiddleware)

        @app.get("/api/data")
        def api_endpoint():
            return {"data": "value"}

        @app.get("/assets/style.css")
        def asset_endpoint():
            return "body { color: black; }"

        with TestClient(app) as client:
            # API route should have no-cache
            response = client.get("/api/data")
            self.assertIn("no-cache", response.headers.get("Cache-Control", ""))

            # Assets should have long cache
            response = client.get("/assets/style.css")
            self.assertIn("max-age=2592000", response.headers.get("Cache-Control", ""))


if __name__ == "__main__":
    unittest.main()
