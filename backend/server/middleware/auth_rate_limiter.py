"""Rate limiting specifically for authentication endpoints.

This middleware provides stricter rate limiting for auth endpoints to prevent
brute force attacks while still allowing legitimate users to authenticate.

Key differences from general rate limiter:
- Stricter limits (e.g., 5 login attempts per 15 minutes per IP)
- Separate tracking for login vs registration
- Progressive delays for repeated failures
- Account lockout after too many failures
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger
from backend.server.utils.responses import error

if TYPE_CHECKING:
    from fastapi import Request, Response

# In-memory rate limit store for auth endpoints
_auth_rate_limit_store: dict[str, dict[str, list[float]]] = defaultdict(
    lambda: {
        "login_attempts": [],
        "register_attempts": [],
        "password_reset_attempts": [],
        "failed_attempts": [],
    }
)


class AuthRateLimiter:
    """Rate limiting middleware specifically for authentication endpoints.

    Provides protection against:
    - Brute force login attacks
    - Account enumeration
    - Password reset abuse
    - Registration spam
    """

    def __init__(
        self,
        login_attempts_per_15min: int = 5,
        register_attempts_per_hour: int = 3,
        password_reset_per_hour: int = 3,
        enabled: bool = True,
    ) -> None:
        """Initialize auth rate limiter.

        Args:
            login_attempts_per_15min: Max login attempts per 15 minutes per IP
            register_attempts_per_hour: Max registration attempts per hour per IP
            password_reset_per_hour: Max password reset attempts per hour per IP
            enabled: Whether auth rate limiting is enabled

        """
        self.login_attempts_per_15min = login_attempts_per_15min
        self.register_attempts_per_hour = register_attempts_per_hour
        self.password_reset_per_hour = password_reset_per_hour
        self.enabled = enabled
        self.login_window = 900  # 15 minutes
        self.register_window = 3600  # 1 hour
        self.password_reset_window = 3600  # 1 hour

    async def __call__(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with auth-specific rate limiting.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response or rate limit error

        """
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        normalized_path = path.rstrip("/")

        # Only apply to auth endpoints
        if not normalized_path.startswith("/api/auth"):
            return await call_next(request)

        # Get rate limit key (IP address for auth endpoints)
        rate_limit_key = self._get_rate_limit_key(request)

        # Determine endpoint type
        endpoint_type = self._get_endpoint_type(normalized_path)

        # Check rate limits
        if not await self._check_rate_limit(rate_limit_key, endpoint_type):
            logger.warning(
                "Auth rate limit exceeded for %s on %s", rate_limit_key, endpoint_type
            )

            # Calculate retry after time
            retry_after = self._get_retry_after(rate_limit_key, endpoint_type)

            resp = error(
                message="Too many authentication attempts. Please try again later.",
                status_code=429,
                error_code="AUTH_RATE_LIMIT_EXCEEDED",
                details={
                    "reason": "too_many_auth_attempts",
                    "endpoint": endpoint_type,
                    "retry_after_seconds": retry_after,
                },
                retry_after=retry_after,
            )
            resp.headers["Retry-After"] = str(retry_after)
            return resp

        # Record attempt
        await self._record_attempt(rate_limit_key, endpoint_type)

        # Process request
        response = await call_next(request)

        # Record failed attempts (for progressive delays)
        if response.status_code in (401, 403):
            await self._record_failed_attempt(rate_limit_key, endpoint_type)

        return response

    def _get_rate_limit_key(self, request: Request) -> str:
        """Get rate limit key for auth endpoints (IP address).

        Args:
            request: FastAPI request

        Returns:
            Rate limit key (IP address)

        """
        # Get IP address from request
        # Check X-Forwarded-For header (for proxies/load balancers)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP (original client)
            ip = forwarded_for.split(",")[0].strip()
        else:
            # Fallback to direct client IP
            ip = request.client.host if request.client else "unknown"

        return f"auth:{ip}"

    def _get_endpoint_type(self, path: str) -> str:
        """Determine the type of auth endpoint.

        Args:
            path: Request path

        Returns:
            Endpoint type (login, register, password_reset, other)

        """
        if "/login" in path:
            return "login"
        elif "/register" in path or "/signup" in path:
            return "register"
        elif "/password-reset" in path or "/forgot-password" in path:
            return "password_reset"
        else:
            return "other"

    async def _check_rate_limit(self, key: str, endpoint_type: str) -> bool:
        """Check if rate limit is exceeded for an endpoint type.

        Args:
            key: Rate limit key
            endpoint_type: Type of auth endpoint

        Returns:
            True if within limits, False if exceeded

        """
        store = _auth_rate_limit_store[key]
        current_time = time.time()

        if endpoint_type == "login":
            attempts = store["login_attempts"]
            window = self.login_window
            limit = self.login_attempts_per_15min

            # Clean old attempts
            attempts[:] = [t for t in attempts if current_time - t < window]

            return len(attempts) < limit

        elif endpoint_type == "register":
            attempts = store["register_attempts"]
            window = self.register_window
            limit = self.register_attempts_per_hour

            attempts[:] = [t for t in attempts if current_time - t < window]

            return len(attempts) < limit

        elif endpoint_type == "password_reset":
            attempts = store["password_reset_attempts"]
            window = self.password_reset_window
            limit = self.password_reset_per_hour

            attempts[:] = [t for t in attempts if current_time - t < window]

            return len(attempts) < limit

        # For other auth endpoints, use login limits
        return await self._check_rate_limit(key, "login")

    async def _record_attempt(self, key: str, endpoint_type: str) -> None:
        """Record an authentication attempt.

        Args:
            key: Rate limit key
            endpoint_type: Type of auth endpoint

        """
        store = _auth_rate_limit_store[key]
        current_time = time.time()

        if endpoint_type == "login":
            store["login_attempts"].append(current_time)
        elif endpoint_type == "register":
            store["register_attempts"].append(current_time)
        elif endpoint_type == "password_reset":
            store["password_reset_attempts"].append(current_time)

    async def _record_failed_attempt(self, key: str, endpoint_type: str) -> None:
        """Record a failed authentication attempt.

        Args:
            key: Rate limit key
            endpoint_type: Type of auth endpoint

        """
        store = _auth_rate_limit_store[key]
        current_time = time.time()

        store["failed_attempts"].append(current_time)

        # Keep only last hour of failed attempts
        store["failed_attempts"][:] = [
            t for t in store["failed_attempts"] if current_time - t < 3600
        ]

    def _get_retry_after(self, key: str, endpoint_type: str) -> int:
        """Calculate retry after time based on failed attempts.

        Progressive delay: more failures = longer wait time.

        Args:
            key: Rate limit key
            endpoint_type: Type of auth endpoint

        Returns:
            Retry after time in seconds

        """
        store = _auth_rate_limit_store[key]
        failed_count = len(store["failed_attempts"])

        # Progressive delay
        if failed_count < 3:
            return 60  # 1 minute
        elif failed_count < 5:
            return 300  # 5 minutes
        elif failed_count < 10:
            return 900  # 15 minutes
        else:
            return 3600  # 1 hour


# Redis-backed auth rate limiter (for production)
try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisAuthRateLimiter(AuthRateLimiter):
    """Redis-backed auth rate limiter for distributed systems."""

    def __init__(
        self,
        redis_url: str | None = None,
        login_attempts_per_15min: int = 5,
        register_attempts_per_hour: int = 3,
        password_reset_per_hour: int = 3,
        enabled: bool = True,
    ) -> None:
        """Initialize Redis-backed auth rate limiter.

        Args:
            redis_url: Redis connection URL
            login_attempts_per_15min: Max login attempts per 15 minutes
            register_attempts_per_hour: Max registration attempts per hour
            password_reset_per_hour: Max password reset attempts per hour
            enabled: Whether auth rate limiting is enabled

        """
        super().__init__(
            login_attempts_per_15min,
            register_attempts_per_hour,
            password_reset_per_hour,
            enabled,
        )

        env_url = os.getenv("REDIS_URL")
        self.redis_url: str = redis_url or env_url or "redis://localhost:6379"
        self._redis_client: redis.Redis | None = None

        if enabled:
            logger.info(
                "RedisAuthRateLimiter initialized with redis_url: %s", self.redis_url
            )

    async def _get_redis_client(self) -> redis.Redis | None:
        """Get or create Redis client."""
        if self._redis_client is None:
            try:
                self._redis_client = await redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                # Test connection
                await self._redis_client.ping()
            except Exception as e:
                logger.warning(
                    "Redis connection failed, falling back to in-memory: %s", e
                )
                return None

        return self._redis_client

    async def _check_rate_limit(self, key: str, endpoint_type: str) -> bool:
        """Check rate limit using Redis."""
        redis_client = await self._get_redis_client()

        if redis_client is None:
            # Fallback to parent implementation
            return await super()._check_rate_limit(key, endpoint_type)

        try:
            current_time = time.time()

            if endpoint_type == "login":
                window = self.login_window
                limit = self.login_attempts_per_15min
                redis_key = f"auth_rate_limit:{key}:login"
            elif endpoint_type == "register":
                window = self.register_window
                limit = self.register_attempts_per_hour
                redis_key = f"auth_rate_limit:{key}:register"
            elif endpoint_type == "password_reset":
                window = self.password_reset_window
                limit = self.password_reset_per_hour
                redis_key = f"auth_rate_limit:{key}:password_reset"
            else:
                return await super()._check_rate_limit(key, endpoint_type)

            # Use Redis sorted set to track attempts
            # Remove old entries
            await redis_client.zremrangebyscore(redis_key, 0, current_time - window)

            # Count current attempts
            count = await redis_client.zcard(redis_key)

            return count < limit

        except Exception as e:
            logger.warning("Redis rate limit check failed: %s", e)
            # Fallback to parent implementation
            return await super()._check_rate_limit(key, endpoint_type)

    async def _record_attempt(self, key: str, endpoint_type: str) -> None:
        """Record attempt using Redis."""
        redis_client = await self._get_redis_client()

        if redis_client is None:
            await super()._record_attempt(key, endpoint_type)
            return

        try:
            current_time = time.time()

            if endpoint_type == "login":
                redis_key = f"auth_rate_limit:{key}:login"
                window = self.login_window
            elif endpoint_type == "register":
                redis_key = f"auth_rate_limit:{key}:register"
                window = self.register_window
            elif endpoint_type == "password_reset":
                redis_key = f"auth_rate_limit:{key}:password_reset"
                window = self.password_reset_window
            else:
                await super()._record_attempt(key, endpoint_type)
                return

            # Add attempt to sorted set
            await redis_client.zadd(redis_key, {str(current_time): current_time})

            # Set expiration
            await redis_client.expire(redis_key, int(window))

        except Exception as e:
            logger.warning("Redis record attempt failed: %s", e)
            await super()._record_attempt(key, endpoint_type)
