"""Rate limiting middleware for Forge API."""

from __future__ import annotations

import os
import random
import time
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger
from backend.api.utils.responses import error

if TYPE_CHECKING:
    from fastapi import Request, Response

# In-memory rate limit store (use Redis in production for distributed systems)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_last_cleanup: float = 0.0
_CLEANUP_INTERVAL: float = 300.0  # Purge expired keys every 5 minutes


_RATE_LIMIT_EXCLUDED = frozenset({"/health", "/api/monitoring/health", "/"})
_RATE_LIMIT_EXCLUDED_PREFIXES = ("/assets", "/api/options")


def _is_auth_path(path: str, normalized_path: str) -> bool:
    """True if path is an auth endpoint."""
    return normalized_path.startswith("/api/auth") or path.startswith("/api/auth")


def _auth_rate_limit_exceeded(auth_key: str, current_time: float) -> bool:
    """True if auth key has exceeded per-minute limit."""
    auth_ts = _rate_limit_store[auth_key]
    auth_ts[:] = [ts for ts in auth_ts if current_time - ts < 60]
    auth_limit = int(os.getenv("AUTH_RATE_LIMIT_PER_MIN", "10"))
    return len(auth_ts) >= auth_limit


def _auth_rate_limit_error_response(auth_key: str):
    """Build 429 response for auth rate limit exceeded."""
    logger.warning("Auth rate limit exceeded for %s", auth_key)
    resp = error(
        message="Too many authentication attempts. Try again later.",
        status_code=429,
        error_code="AUTH_RATE_LIMIT_EXCEEDED",
        details={"reason": "auth_brute_force_protection"},
        retry_after=60,
    )
    resp.headers["Retry-After"] = "60"
    return resp


def _record_auth_request(auth_key: str, current_time: float) -> None:
    """Record auth request timestamp."""
    _rate_limit_store[auth_key].append(current_time)


def _is_rate_limit_excluded_path(path: str, normalized_path: str) -> bool:
    """True if path should skip rate limiting."""
    if normalized_path in _RATE_LIMIT_EXCLUDED:
        return True
    return path.startswith(_RATE_LIMIT_EXCLUDED_PREFIXES)


def _rate_limit_error_response(rate_limit_key: str):
    """Build 429 rate limit exceeded response."""
    logger.warning("Rate limit exceeded for %s", rate_limit_key)
    resp = error(
        message="Rate limit exceeded. Please try again later.",
        status_code=429,
        error_code="RATE_LIMIT_EXCEEDED",
        details={"reason": "too_many_requests"},
        retry_after=60,
    )
    resp.headers["Retry-After"] = "60"
    return resp


def _purge_expired_keys(max_age: float = 3600.0) -> None:
    """Remove keys whose newest timestamp is older than *max_age* seconds."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    stale = _find_stale_rate_limit_keys(max_age, now)
    for key in stale:
        del _rate_limit_store[key]


def _trim_to_window(timestamps: list[float], now: float, window: float) -> None:
    """Trim timestamps to those within window of now (mutates in place)."""
    timestamps[:] = [ts for ts in timestamps if now - ts < window]


def _exceeds_hourly_limit(timestamps: list[float], limit: int) -> bool:
    """True if timestamps count meets or exceeds hourly limit."""
    return len(timestamps) >= limit


def _exceeds_burst_limit(
    timestamps: list[float], now: float, burst_window: float, burst_limit: int
) -> bool:
    """True if recent timestamps (within burst_window) meet or exceed burst limit."""
    recent = [ts for ts in timestamps if now - ts < burst_window]
    return len(recent) >= burst_limit


def _find_stale_rate_limit_keys(max_age: float, now: float) -> list[str]:
    """Return keys with no timestamps or newest timestamp older than max_age."""
    return [
        key
        for key, timestamps in _rate_limit_store.items()
        if not timestamps or (now - max(timestamps)) > max_age
    ]


class RateLimiter:
    """Rate limiting middleware for API endpoints."""

    def __init__(
        self,
        requests_per_hour: int = 100,
        burst_limit: int = 20,
        enabled: bool = True,
    ) -> None:
        """Initialize rate limiter.

        Args:
            requests_per_hour: Maximum requests allowed per hour
            burst_limit: Maximum requests allowed in a 1-minute window
            enabled: Whether rate limiting is enabled

        """
        self.requests_per_hour = requests_per_hour
        self.burst_limit = burst_limit
        self.enabled = enabled
        self.hour_window = 3600  # 1 hour in seconds
        self.burst_window = 60  # 1 minute in seconds

    async def __call__(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with rate limiting."""
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        normalized_path = path.rstrip("/")
        current_time = time.time()

        auth_result = await self._maybe_handle_auth_path(request, path, normalized_path, current_time, call_next)
        if auth_result is not None:
            return auth_result

        if _is_rate_limit_excluded_path(path, normalized_path):
            return await call_next(request)

        rate_limit_key = await self._get_rate_limit_key(request)
        if not await self._check_rate_limit(rate_limit_key):
            return _rate_limit_error_response(rate_limit_key)

        response = await call_next(request)
        remaining = await self._get_remaining_requests(rate_limit_key)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_hour)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time() + self.hour_window))
        return response

    async def _maybe_handle_auth_path(
        self, request: Request, path: str, normalized_path: str, current_time: float, call_next: Callable
    ):
        """Handle auth paths with stricter rate limit. Returns response or None if not auth path."""
        if not _is_auth_path(path, normalized_path):
            return None
        auth_key = f"auth:{await self._get_rate_limit_key(request)}"
        if _auth_rate_limit_exceeded(auth_key, current_time):
            return _auth_rate_limit_error_response(auth_key)
        _record_auth_request(auth_key, current_time)
        return await call_next(request)

    async def _get_rate_limit_key(self, request: Request) -> str:
        """Get rate limit key from request.

        Tries to use user_id from auth, falls back to IP address.

        Args:
            request: FastAPI request

        Returns:
            Rate limit key (user_id or IP)

        """
        # Try to get user_id from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"

        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Use first IP in X-Forwarded-For chain
            client_ip = forwarded_for.split(",")[0].strip()

        try:
            import hashlib

            hashed = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:12]
            return "ip:" + hashed
        except Exception:
            return "ip:unknown"

    async def _check_rate_limit(self, key: str) -> bool:
        """Check if request is within rate limits."""
        current_time = time.time()
        _purge_expired_keys(max_age=self.hour_window)

        timestamps = _rate_limit_store[key]
        _trim_to_window(timestamps, current_time, self.hour_window)

        if _exceeds_hourly_limit(timestamps, self.requests_per_hour):
            return False
        if _exceeds_burst_limit(timestamps, current_time, self.burst_window, self.burst_limit):
            return False

        timestamps.append(current_time)
        return True

    async def _get_remaining_requests(self, key: str) -> int:
        """Get remaining requests for key.

        Args:
            key: Rate limit key

        Returns:
            Number of remaining requests in current window

        """
        current_time = time.time()
        timestamps = _rate_limit_store[key]

        # Count requests in current hour
        hour_requests = [
            ts for ts in timestamps if current_time - ts < self.hour_window
        ]

        return max(0, self.requests_per_hour - len(hour_requests))


# Endpoint-specific rate limiters
class EndpointRateLimiter:
    """Rate limiter with endpoint-specific limits."""

    # Define limits per endpoint pattern
    # 🚀 PRODUCTION FIX: Configurable limits via environment variables
    @staticmethod
    def _get_default_limits():
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
        """Initialize endpoint-specific rate limiter.

        Args:
            enabled: Whether rate limiting is enabled

        """
        self.enabled = enabled
        # Get default limits from environment variables
        default_limits = self._get_default_limits()

        # Define limits per endpoint pattern
        self.LIMITS = {
            "/api/conversations": default_limits,  # Use env-configured limits
            "/api/database": default_limits,
            "/api/memory": default_limits,
            "/api/monitoring": default_limits,  # ← Add monitoring endpoints
            "default": default_limits,  # Default limits from environment
        }

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Process request with endpoint-specific rate limiting.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response or rate limit error

        """
        if not self.enabled:
            return await call_next(request)

        # Skip rate limiting for authentication endpoints
        # Auth endpoints are handled by RateLimiter's own auth-specific limiter,
        # so we delegate to it rather than skipping entirely.
        path = request.url.path
        normalized_path = path.rstrip("/")

        # Exclude public options endpoints (called frequently on page load)
        if normalized_path.startswith("/api/options") or path.startswith(
            "/api/options"
        ):
            return await call_next(request)

        # Get endpoint-specific limits
        path = request.url.path
        limits = self._get_limits_for_path(path)
        requests_per_hour, burst_limit = limits

        # Create rate limiter with endpoint-specific limits
        limiter = RateLimiter(
            requests_per_hour=requests_per_hour,
            burst_limit=burst_limit,
            enabled=self.enabled,
        )

        return await limiter(request, call_next)

    def _get_limits_for_path(self, path: str) -> tuple[int, int]:
        """Get rate limits for specific path.

        Args:
            path: Request path

        Returns:
            Tuple of (requests_per_hour, burst_limit)

        """
        for pattern, limits in self.LIMITS.items():
            if pattern in path:
                return limits

        return self.LIMITS["default"]


# Redis-backed rate limiter for production (optional)
try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("Redis not available, using in-memory rate limiting")


class RedisRateLimiter(RateLimiter):
    """Redis-backed rate limiter for distributed systems."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        requests_per_hour: int | None = None,  # 🚀 Now reads from env vars
        burst_limit: int | None = None,  # 🚀 Now reads from env vars
        enabled: bool = True,
    ) -> None:
        """Initialize Redis rate limiter.

        Args:
            redis_url: Redis connection URL
            requests_per_hour: Maximum requests allowed per hour (None = use env var)
            burst_limit: Maximum requests allowed in 1-minute window (None = use env var)
            enabled: Whether rate limiting is enabled

        """
        # 🚀 PRODUCTION FIX: Read from environment variables if not provided
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
        self._redis_client: redis.Redis | None = None

    async def _get_redis_client(self) -> redis.Redis | None:
        """Get or create Redis client.

        Returns:
            Redis client or None if unavailable

        """
        if not REDIS_AVAILABLE:
            return None

        if self._redis_client is None:
            try:
                self._redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                )
                # Test connection
                await self._redis_client.ping()
                logger.info("Connected to Redis for rate limiting")
            except Exception as e:
                logger.warning(
                    "Failed to connect to Redis: %s. Falling back to in-memory.", e
                )
                self._redis_client = None

        return self._redis_client

    async def _check_rate_limit(self, key: str) -> bool:
        """Check rate limit using Redis.

        Args:
            key: Rate limit key

        Returns:
            True if within limits, False if exceeded

        """
        redis_client = await self._get_redis_client()

        # Fall back to in-memory if Redis unavailable
        if redis_client is None:
            return await super()._check_rate_limit(key)

        try:
            return await self._check_rate_limit_redis(redis_client, key)
        except Exception as exc:
            logger.error("Redis rate limit check failed: %s. Allowing request.", exc)
            self._instrument_failure(key, exc)
            return True

    async def _check_rate_limit_redis(
        self,
        redis_client: redis.Redis,
        key: str,
    ) -> bool:
        """Core Redis rate limit logic separated for readability."""
        current_time = int(time.time())
        redis_key = f"ratelimit:{key}"

        await redis_client.zremrangebyscore(
            redis_key,
            0,
            current_time - self.hour_window,
        )

        hour_count = await redis_client.zcount(
            redis_key,
            current_time - self.hour_window,
            current_time,
        )
        if hour_count >= self.requests_per_hour:
            self._record_rate_limit_span(
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
            self._record_rate_limit_span(
                key,
                allowed=False,
                hour_count=hour_count,
                burst_count=burst_count,
                reason="burst_limit",
            )
            return False

        await self._record_request(redis_client, redis_key, current_time)
        await redis_client.expire(redis_key, self.hour_window)

        self._record_rate_limit_span(
            key,
            allowed=True,
            hour_count=hour_count + 1,
            burst_count=burst_count + 1,
        )
        return True

    async def _record_request(
        self,
        redis_client: redis.Redis,
        redis_key: str,
        timestamp: int,
    ) -> None:
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

    def _record_rate_limit_span(
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
                    span, key, allowed, hour_count, burst_count,
                    self.requests_per_hour, self.burst_limit, reason, exc
                )
        except Exception:
            return


def _set_rate_limit_span_attrs(
    span,
    key: str,
    allowed: bool,
    hour_count: int | None,
    burst_count: int | None,
    hour_limit: int,
    burst_limit: int,
    reason: str | None,
    exc: Exception | None,
) -> None:
    """Set OTEL span attributes for rate limit decision."""
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
    if exc:
        span.set_attribute("error", True)
        span.record_exception(exc)

    def _instrument_failure(self, key: str, exc: Exception) -> None:
        """Record OTEL span for Redis failures."""
        self._record_rate_limit_span(
            key,
            allowed=True,  # fail-open behaviour
            hour_count=None,
            burst_count=None,
            reason="error",
            exc=exc,
        )

    async def _get_remaining_requests(self, key: str) -> int:
        """Get remaining requests using Redis.

        Args:
            key: Rate limit key

        Returns:
            Number of remaining requests

        """
        redis_client = await self._get_redis_client()

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

        except Exception as e:
            logger.error("Redis remaining count failed: %s", e)
            return self.requests_per_hour  # Return max if Redis fails
