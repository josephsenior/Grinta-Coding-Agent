"""Custom middleware components for the Forge FastAPI server."""

import asyncio
import os
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
from starlette.types import ASGIApp


class LocalhostCORSMiddleware(CORSMiddleware):
    """Custom CORS middleware that allows any request from localhost/127.0.0.1 domains,.

    while using standard CORS rules for other origins.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Configure allowed origins while whitelisting localhost domains."""
        if allow_origins_str := os.getenv("PERMITTED_CORS_ORIGINS"):
            allow_origins = tuple(
                origin.strip() for origin in allow_origins_str.split(",")
            )
        else:
            allow_origins = ()
        super().__init__(
            app,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def is_allowed_origin(self, origin: str) -> bool:
        """Permit localhost/127.0.0.1 regardless of configured allow_origins."""
        if origin:
            parsed = urlparse(origin)
            hostname = parsed.hostname or ""
            # Always allow localhost and 127.0.0.1 regardless of allow_origins setting
            if hostname in ["localhost", "127.0.0.1"]:
                return True
        result: bool = super().is_allowed_origin(origin)
        return result


class CacheControlMiddleware(BaseHTTPMiddleware):
    """Middleware to disable caching for all routes by adding appropriate headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Set cache-control headers for static assets and dynamic responses."""
        response = await call_next(request)
        if request.url.path.startswith("/assets"):
            response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        else:
            response.headers["Cache-Control"] = (
                "no-cache, no-store, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


class InMemoryRateLimiter:
    """Naive in-memory rate limiter suitable for single-process deployments."""

    history: dict[str, list[datetime]]
    requests: int
    seconds: int
    sleep_seconds: int

    def __init__(
        self, requests: int = 2, seconds: int = 1, sleep_seconds: int = 1
    ) -> None:
        """Configure rate limits and initialize request history."""
        self.requests = requests
        self.seconds = seconds
        self.sleep_seconds = sleep_seconds
        self.history = defaultdict(list)
        self.sleep_seconds = sleep_seconds

    def _clean_old_requests(self, key: str) -> None:
        """Drop timestamps that fall outside the configured window."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.seconds)
        self.history[key] = [ts for ts in self.history[key] if ts > cutoff]
        if not self.history[key]:
            del self.history[key]

    async def __call__(self, request: Request) -> bool:
        """Return True if request should proceed (may sleep), False if rejected."""
        client = request.client
        key = client.host if client and client.host else "unknown"
        now = datetime.now()
        self._clean_old_requests(key)
        self.history[key].append(now)
        if len(self.history[key]) > self.requests * 2:
            return False
        if len(self.history[key]) > self.requests:
            if self.sleep_seconds <= 0:
                return False
            await asyncio.sleep(self.sleep_seconds)
            return True
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware wrapper around the in-memory rate limiter."""

    def __init__(self, app: ASGIApp, rate_limiter: InMemoryRateLimiter) -> None:
        """Store rate limiter instance for reuse per request."""
        super().__init__(app)
        self.rate_limiter = rate_limiter

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Apply rate limiting, falling back to next handler when within limits."""
        if not self.is_rate_limited_request(request):
            return await call_next(request)
        ok = await self.rate_limiter(request)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"message": "Too many requests"},
                headers={"Retry-After": "1"},
            )
        return await call_next(request)

    def is_rate_limited_request(self, request: StarletteRequest) -> bool:
        """Check if the incoming request path should be subject to rate limiting."""
        return not request.url.path.startswith("/assets")
