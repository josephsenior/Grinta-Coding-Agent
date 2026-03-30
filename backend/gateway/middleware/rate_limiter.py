"""Rate limiting middleware for App API."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

logger = logging.getLogger(__name__)

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_last_cleanup = 0.0
_rate_limit_lock = asyncio.Lock()


def _purge_expired_keys(max_age: float = 3600.0) -> None:
    """Remove stale rate-limit keys from the in-memory store."""
    now = time.time()
    module_state = globals()
    last_cleanup = module_state.get("_last_cleanup", 0.0)
    if now - last_cleanup < max_age:
        return

    cutoff = now - max_age
    stale_keys = [
        key
        for key, timestamps in _rate_limit_store.items()
        if not timestamps or max(timestamps) < cutoff
    ]
    for key in stale_keys:
        _rate_limit_store.pop(key, None)

    module_state["_last_cleanup"] = now


def _set_rate_limit_span_attrs(
    span: Any,
    key: str,
    allowed: bool,
    hour_count: int | None,
    burst_count: int | None,
    hour_limit: int,
    burst_limit: int,
    reason: str | None,
    exc: Exception | None,
) -> None:
    """Set OTEL span attributes for rate-limit decisions."""
    span.set_attribute("ratelimit.key", key)
    span.set_attribute("ratelimit.allowed", allowed)
    if hour_count is not None:
        span.set_attribute("ratelimit.hour.count", int(hour_count))
        span.set_attribute("ratelimit.hour.limit", int(hour_limit))
    if burst_count is not None:
        span.set_attribute("ratelimit.burst.count", int(burst_count))
        span.set_attribute("ratelimit.burst.limit", int(burst_limit))
    if reason:
        span.set_attribute("ratelimit.reason", reason)
    if exc is not None:
        span.set_attribute("error", True)
        span.record_exception(exc)


class RateLimiter:
    """Naive in-memory rate limiter suitable for single-process deployments."""

    def __init__(
        self,
        requests_per_hour: int = 100,
        burst_limit: int = 20,
        enabled: bool = True,
    ) -> None:
        self.requests_per_hour = requests_per_hour
        self.burst_limit = burst_limit
        self.enabled = enabled
        self.hour_window = 3600
        self.burst_window = 60

    async def _get_rate_limit_key(self, request: Request) -> str:
        """Derive a stable key from authenticated user or client address."""
        state = getattr(request, "state", None)
        user_id = getattr(state, "user_id", None)
        if user_id:
            return f"user:{user_id}"

        headers = getattr(request, "headers", {})
        forwarded_for = None
        if hasattr(headers, "get"):
            forwarded_for = headers.get("X-Forwarded-For") or headers.get(
                "x-forwarded-for"
            )

        if forwarded_for:
            client_ip = str(forwarded_for).split(",", 1)[0].strip()
        else:
            client = getattr(request, "client", None)
            client_ip = getattr(client, "host", None) or "unknown"

        return f"ip:{client_ip}"

    def _filtered_timestamps(self, key: str, window_seconds: int) -> list[float]:
        """Return timestamps within the requested window and compact the store."""
        now = time.time()
        timestamps = _rate_limit_store.get(key, [])
        fresh = [ts for ts in timestamps if now - ts < window_seconds]
        if fresh:
            _rate_limit_store[key] = fresh
        else:
            _rate_limit_store.pop(key, None)
        return fresh

    async def _check_rate_limit(self, key: str) -> bool:
        """Check whether a request is within configured limits."""
        _purge_expired_keys(self.hour_window)

        async with _rate_limit_lock:
            now = time.time()
            timestamps = self._filtered_timestamps(key, self.hour_window)
            hour_count = len(timestamps)
            if hour_count >= self.requests_per_hour:
                return False

            burst_count = len([ts for ts in timestamps if now - ts < self.burst_window])
            if burst_count >= self.burst_limit:
                return False

            timestamps.append(now)
            _rate_limit_store[key] = timestamps
            return True

    async def _get_remaining_requests(self, key: str) -> int:
        """Return the number of requests left in the hourly window."""
        timestamps = self._filtered_timestamps(key, self.hour_window)
        return max(0, self.requests_per_hour - len(timestamps))

    async def __call__(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Apply rate limiting and attach standard rate-limit headers."""
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        normalized_path = path.rstrip("/")
        if normalized_path == "/health" or path.startswith("/assets"):
            return await call_next(request)

        key = await self._get_rate_limit_key(request)
        allowed = await self._check_rate_limit(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"message": "Too many requests"},
                headers={"Retry-After": "1"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_hour)
        response.headers["X-RateLimit-Remaining"] = str(
            await self._get_remaining_requests(key)
        )
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.hour_window)
        return response


class EndpointRateLimiter:
    """Rate limiter with endpoint-specific limits."""

    @staticmethod
    def _get_default_limits() -> tuple[int, int]:
        """Get default rate limits from environment variables."""
        requests_per_hour = int(os.getenv("RATE_LIMIT_REQUESTS", "1000"))
        burst_limit = int(os.getenv("RATE_LIMIT_BURST", "100"))
        logger.info(
            "Rate limiting configured: %s req/hour, %s burst",
            requests_per_hour,
            burst_limit,
        )
        return requests_per_hour, burst_limit

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        default_limits = self._get_default_limits()
        self.LIMITS = {
            "/api/conversations": default_limits,
            "/api/database": default_limits,
            "/api/memory": default_limits,
            "/api/monitoring": default_limits,
            "default": default_limits,
        }

    async def __call__(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Apply endpoint-specific limits before delegating to RateLimiter."""
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        normalized_path = path.rstrip("/")
        if normalized_path.startswith("/api/options") or path.startswith("/api/options"):
            return await call_next(request)

        requests_per_hour, burst_limit = self._get_limits_for_path(path)
        limiter = RateLimiter(
            requests_per_hour=requests_per_hour,
            burst_limit=burst_limit,
            enabled=self.enabled,
        )
        return await limiter(request, call_next)

    def _get_limits_for_path(self, path: str) -> tuple[int, int]:
        """Get rate limits for specific path."""
        for pattern, limits in self.LIMITS.items():
            if pattern in path:
                return limits
        return self.LIMITS["default"]


_redis_asyncio: Any = None
try:
    import redis.asyncio as redis_ai

    _redis_asyncio = redis_ai
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("Redis not available, using in-memory rate limiting")


class RedisRateLimiter(RateLimiter):
    """Redis-backed rate limiter for distributed systems."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        requests_per_hour: int | None = None,
        burst_limit: int | None = None,
        enabled: bool = True,
    ) -> None:
        if requests_per_hour is None:
            requests_per_hour = int(os.getenv("RATE_LIMIT_REQUESTS", "1000"))
        if burst_limit is None:
            burst_limit = int(os.getenv("RATE_LIMIT_BURST", "100"))

        logger.info(
            "RedisRateLimiter configured: %s req/hour, %s burst",
            requests_per_hour,
            burst_limit,
        )
        super().__init__(requests_per_hour, burst_limit, enabled)
        self.redis_url = redis_url
        self._redis_client: Any | None = None

    async def get_redis_client(self) -> Any | None:
        """Get or create Redis client."""
        if not REDIS_AVAILABLE or _redis_asyncio is None:
            return None

        if self._redis_client is None:
            try:
                self._redis_client = _redis_asyncio.from_url(
                    self.redis_url,
                    decode_responses=True,
                )
                await self._redis_client.ping()
                logger.info("Connected to Redis for rate limiting")
            except Exception as exc:
                logger.warning(
                    "Failed to connect to Redis: %s. Falling back to in-memory.", exc
                )
                self._redis_client = None

        return self._redis_client

    async def _check_rate_limit(self, key: str) -> bool:
        """Check rate limit using Redis."""
        redis_client = await self.get_redis_client()
        if redis_client is None:
            return await super()._check_rate_limit(key)

        try:
            return await self._check_rate_limit_redis(redis_client, key)
        except Exception as exc:
            logger.error("Redis rate limit check failed: %s. Allowing request.", exc)
            self.instrument_failure(key, exc)
            return True

    async def _check_rate_limit_redis(self, redis_client: Any, key: str) -> bool:
        """Core Redis rate limit logic separated for readability."""
        current_time = int(time.time())
        redis_key = f"ratelimit:{key}"

        await redis_client.zremrangebyscore(redis_key, 0, current_time - self.hour_window)

        hour_count = await redis_client.zcount(
            redis_key,
            current_time - self.hour_window,
            current_time,
        )
        if hour_count >= self.requests_per_hour:
            self.record_rate_limit_span(
                key,
                allowed=False,
                hour_count=hour_count,
                burst_count=None,
                reason="hour_limit",
            )
            return False

        burst_count = await redis_client.zcount(
            redis_key,
            current_time - self.burst_window,
            current_time,
        )
        if burst_count >= self.burst_limit:
            logger.debug(
                "Burst limit exceeded: %s/%s for %s", burst_count, self.burst_limit, key
            )
            self.record_rate_limit_span(
                key,
                allowed=False,
                hour_count=hour_count,
                burst_count=burst_count,
                reason="burst_limit",
            )
            return False

        await self._record_request(redis_client, redis_key, current_time)
        await redis_client.expire(redis_key, self.hour_window)

        self.record_rate_limit_span(
            key,
            allowed=True,
            hour_count=hour_count + 1,
            burst_count=burst_count + 1,
        )
        return True

    async def _record_request(self, redis_client: Any, redis_key: str, timestamp: int) -> None:
        """Store the current request timestamp with microsecond uniqueness."""
        import uuid

        unique_id = f"{timestamp}:{uuid.uuid4()}"
        await redis_client.zadd(redis_key, {unique_id: timestamp})

    def _should_trace(self) -> bool:
        """Decide if we should emit an OTEL span based on env + sampling."""
        enabled = os.getenv(
            "OTEL_INSTRUMENT_REDIS", os.getenv("OTEL_ENABLED", "false")
        ).lower() in ("true", "1", "yes")
        if not enabled:
            return False

        try:
            sample_rate = float(
                os.getenv("OTEL_SAMPLE_REDIS", os.getenv("OTEL_SAMPLE_DEFAULT", "1.0"))
            )
        except Exception:
            sample_rate = 1.0

        sample_rate = max(0.0, min(1.0, sample_rate))
        return random.random() < sample_rate

    def record_rate_limit_span(
        self,
        key: str,
        *,
        allowed: bool,
        hour_count: int | None,
        burst_count: int | None,
        reason: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        """Emit a single structured OTEL span for rate limiting decisions."""
        if not self._should_trace():
            return

        from backend.utils.otel_utils import redis_span

        try:
            with redis_span("rate_limit.check") as span:
                if span is None:
                    return
                _set_rate_limit_span_attrs(
                    span,
                    key,
                    allowed,
                    hour_count,
                    burst_count,
                    self.requests_per_hour,
                    self.burst_limit,
                    reason,
                    exc,
                )
        except Exception:
            return

    def instrument_failure(self, key: str, exc: Exception) -> None:
        """Record OTEL span for Redis failures."""
        self.record_rate_limit_span(
            key,
            allowed=True,
            hour_count=None,
            burst_count=None,
            reason="error",
            exc=exc,
        )

    async def get_remaining_requests(self, key: str) -> int:
        """Get remaining requests using Redis."""
        redis_client = await self.get_redis_client()
        if redis_client is None:
            return await super()._get_remaining_requests(key)

        try:
            current_time = int(time.time())
            redis_key = f"ratelimit:{key}"
            hour_count = await redis_client.zcount(
                redis_key,
                current_time - self.hour_window,
                current_time,
            )
            return max(0, self.requests_per_hour - hour_count)
        except Exception as exc:
            logger.error("Redis remaining count failed: %s", exc)
            return self.requests_per_hour

