"""Resource quota management middleware.

Tracks and enforces resource limits per user including:
- Concurrent conversations
- Memory usage
- CPU usage
- Disk space
- API call rates
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.logger import forge_logger as logger
from backend.api.utils.responses import error

if TYPE_CHECKING:
    pass

# In-memory quota tracking (use Redis in production for distributed systems)
_quota_store: dict[str, dict[str, Any]] = defaultdict(dict)


@dataclass
class ResourceQuota:
    """Resource quota configuration per user plan."""

    max_concurrent_conversations: int = 5
    max_runtime_memory_mb: int = 2048
    max_runtime_cpu_percent: int = 50
    max_disk_space_mb: int = 10240
    max_api_calls_per_minute: int = 60
    max_api_calls_per_hour: int = 1000
    max_daily_cost_usd: float = 10.0


# Default quota plans
QUOTA_PLANS = {
    "free": ResourceQuota(
        max_concurrent_conversations=3,
        max_runtime_memory_mb=1024,
        max_runtime_cpu_percent=25,
        max_disk_space_mb=5120,
        max_api_calls_per_minute=30,
        max_api_calls_per_hour=500,
        max_daily_cost_usd=1.0,
    ),
    "pro": ResourceQuota(
        max_concurrent_conversations=10,
        max_runtime_memory_mb=4096,
        max_runtime_cpu_percent=75,
        max_disk_space_mb=20480,
        max_api_calls_per_minute=120,
        max_api_calls_per_hour=5000,
        max_daily_cost_usd=50.0,
    ),
    "enterprise": ResourceQuota(
        max_concurrent_conversations=50,
        max_runtime_memory_mb=16384,
        max_runtime_cpu_percent=100,
        max_disk_space_mb=102400,
        max_api_calls_per_minute=300,
        max_api_calls_per_hour=50000,
        max_daily_cost_usd=500.0,
    ),
}


class ResourceQuotaMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce resource quotas per user."""

    def __init__(self, app, enabled: bool = True):
        """Initialize resource quota middleware.

        Args:
            app: The ASGI application (required by BaseHTTPMiddleware)
            enabled: Whether quota enforcement is enabled
        """
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        """Process request with resource quota checks."""
        if not self.enabled:
            return await call_next(request)

        # Skip quota checks for public endpoints and authentication endpoints
        # Authentication endpoints should never be rate-limited to allow users to register/login
        # Public options endpoints are also excluded as they're called frequently on page load
        path = request.url.path

        # Normalize path (remove trailing slash and query params for comparison)
        normalized_path = path.split("?")[0].rstrip("/")

        # Check exclusions (must be checked FIRST before any rate limiting)
        # Use both normalized and original path for maximum compatibility
        is_excluded = (
            normalized_path
            in {
                "/health",
                "/api/monitoring/health",
                "/alive",
                "/docs",
                "/redoc",
                "/openapi.json",
            }
            or normalized_path.startswith(("/api/auth", "/api/options"))
            or path.startswith(("/api/auth", "/api/options"))
        )

        if is_excluded:
            logger.debug(
                "Resource quota check skipped for excluded path: %s (normalized: %s)",
                path,
                normalized_path,
            )
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # Anonymous users get free tier limits
            user_id = "anonymous"

        # Get user's quota plan (default to free)
        user_plan = self._get_user_plan(user_id)
        quota = QUOTA_PLANS.get(user_plan, QUOTA_PLANS["free"])

        # Check API call rate limits
        rate_limit_error = self._check_rate_limits(user_id, quota)
        if rate_limit_error:
            return rate_limit_error

        # Track API call
        self._track_api_call(user_id)

        # Add quota headers to response
        response = await call_next(request)
        response.headers["X-Quota-Plan"] = user_plan
        response.headers["X-Quota-Remaining-Calls"] = str(
            self._get_remaining_calls(user_id, quota)
        )

        return response

    def _get_user_plan(self, user_id: str) -> str:
        """Get user's quota plan (from user settings or default to free)."""
        # TODO: Integrate with user settings/store
        # For now, return free for all users
        return os.getenv("DEFAULT_QUOTA_PLAN", "free")

    def _check_rate_limits(
        self, user_id: str, quota: ResourceQuota
    ) -> JSONResponse | None:
        """Check if user has exceeded rate limits."""
        now = time.time()
        user_quota = _quota_store[user_id]

        # Initialize tracking if needed
        if "api_calls" not in user_quota:
            user_quota["api_calls"] = []

        api_calls = user_quota["api_calls"]

        # Clean old calls (older than 1 hour)
        api_calls[:] = [call_time for call_time in api_calls if now - call_time < 3600]

        # Check hourly limit
        if len(api_calls) >= quota.max_api_calls_per_hour:
            return error(
                message="API call rate limit exceeded (hourly)",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                error_code="RATE_LIMIT_EXCEEDED",
                details={
                    "limit": quota.max_api_calls_per_hour,
                    "window": "1 hour",
                    "retry_after": 3600 - int(now - api_calls[0])
                    if api_calls
                    else 3600,
                },
            )

        # Check per-minute limit (last 60 seconds)
        recent_calls = [call_time for call_time in api_calls if now - call_time < 60]
        if len(recent_calls) >= quota.max_api_calls_per_minute:
            return error(
                message="API call rate limit exceeded (per minute)",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                error_code="RATE_LIMIT_EXCEEDED",
                details={
                    "limit": quota.max_api_calls_per_minute,
                    "window": "1 minute",
                    "retry_after": 60 - int(now - recent_calls[0])
                    if recent_calls
                    else 60,
                },
            )

        return None

    def _track_api_call(self, user_id: str) -> None:
        """Track an API call for rate limiting."""
        now = time.time()
        user_quota = _quota_store[user_id]
        if "api_calls" not in user_quota:
            user_quota["api_calls"] = []
        user_quota["api_calls"].append(now)

    def _get_remaining_calls(self, user_id: str, quota: ResourceQuota) -> int:
        """Get remaining API calls for the current hour."""
        now = time.time()
        user_quota = _quota_store.get(user_id, {})
        api_calls = user_quota.get("api_calls", [])
        recent_calls = [call_time for call_time in api_calls if now - call_time < 3600]
        return max(0, quota.max_api_calls_per_hour - len(recent_calls))


def get_user_quota(user_id: str) -> ResourceQuota:
    """Get resource quota for a user."""
    plan = os.getenv("DEFAULT_QUOTA_PLAN", "free")
    return QUOTA_PLANS.get(plan, QUOTA_PLANS["free"])


def check_conversation_quota(
    user_id: str, current_count: int
) -> tuple[bool, str | None]:
    """Check if user can create another conversation.

    Returns:
        Tuple of (allowed, error_message)
    """
    quota = get_user_quota(user_id)
    if current_count >= quota.max_concurrent_conversations:
        return (
            False,
            f"Maximum concurrent conversations ({quota.max_concurrent_conversations}) reached",
        )
    return True, None
