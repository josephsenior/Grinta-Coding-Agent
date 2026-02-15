"""Cost-based quota system for LLM API usage.

Tracks actual $ spent instead of just request counts.
Supports per-user and per-plan quotas (free, pro, enterprise).

The Redis-backed variant lives in ``redis_cost_quota.py``; the global
factory and ``record_llm_cost`` helper are in ``cost_recording.py``.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from backend.core.constants import (
    DEFAULT_QUOTA_DAY_WINDOW,
    DEFAULT_QUOTA_HOUR_WINDOW,
    DEFAULT_QUOTA_MONTH_WINDOW,
    ENTERPRISE_PLAN_BURST_LIMIT,
    ENTERPRISE_PLAN_DAILY_LIMIT,
    ENTERPRISE_PLAN_MONTHLY_LIMIT,
    FREE_PLAN_BURST_LIMIT,
    FREE_PLAN_DAILY_LIMIT,
    FREE_PLAN_MONTHLY_LIMIT,
    PRO_PLAN_BURST_LIMIT,
    PRO_PLAN_DAILY_LIMIT,
    PRO_PLAN_MONTHLY_LIMIT,
    QUOTA_EXEMPT_PATH_PREFIXES,
    QUOTA_EXEMPT_PATHS,
)
from backend.core.enums import QuotaPlan
from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    from fastapi import Request, Response


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QuotaConfig:
    """Quota configuration for a plan."""

    plan: QuotaPlan
    daily_limit: float  # $ per day
    monthly_limit: float  # $ per month
    burst_limit: float  # $ per hour


@dataclass(frozen=True)
class RedisQuotaKeys:
    """Helper container for Redis key names used per user."""

    daily: str
    monthly: str
    daily_reset: str
    monthly_reset: str


# ---------------------------------------------------------------------------
# In-memory cost store & plan configs
# ---------------------------------------------------------------------------

_cost_store: dict[str, dict[str, float]] = defaultdict(
    lambda: {
        "daily_cost": 0.0,
        "monthly_cost": 0.0,
        "last_reset_day": time.time(),
        "last_reset_month": time.time(),
    }
)

QUOTA_CONFIGS = {
    QuotaPlan.FREE: QuotaConfig(
        plan=QuotaPlan.FREE,
        daily_limit=FREE_PLAN_DAILY_LIMIT,
        monthly_limit=FREE_PLAN_MONTHLY_LIMIT,
        burst_limit=FREE_PLAN_BURST_LIMIT,
    ),
    QuotaPlan.PRO: QuotaConfig(
        plan=QuotaPlan.PRO,
        daily_limit=PRO_PLAN_DAILY_LIMIT,
        monthly_limit=PRO_PLAN_MONTHLY_LIMIT,
        burst_limit=PRO_PLAN_BURST_LIMIT,
    ),
    QuotaPlan.ENTERPRISE: QuotaConfig(
        plan=QuotaPlan.ENTERPRISE,
        daily_limit=ENTERPRISE_PLAN_DAILY_LIMIT,
        monthly_limit=ENTERPRISE_PLAN_MONTHLY_LIMIT,
        burst_limit=ENTERPRISE_PLAN_BURST_LIMIT,
    ),
    QuotaPlan.UNLIMITED: QuotaConfig(
        plan=QuotaPlan.UNLIMITED,
        daily_limit=float("inf"),
        monthly_limit=float("inf"),
        burst_limit=float("inf"),
    ),
}


# ---------------------------------------------------------------------------
# In-memory middleware (base class)
# ---------------------------------------------------------------------------


class CostQuotaMiddleware:
    """Middleware for enforcing cost-based quotas.

    Tracks actual $ spent on LLM API calls and enforces per-plan limits.
    More accurate than request-based rate limiting for LLM usage.
    """

    def __init__(
        self,
        enabled: bool = True,
        default_plan: QuotaPlan = QuotaPlan.FREE,
    ) -> None:
        """Initialize cost quota middleware.

        Args:
            enabled: Whether cost quota enforcement is enabled
            default_plan: Default plan for users without a plan

        """
        self.enabled = enabled
        self.default_plan = default_plan
        self.hour_window = DEFAULT_QUOTA_HOUR_WINDOW
        self.day_window = DEFAULT_QUOTA_DAY_WINDOW
        self.month_window = DEFAULT_QUOTA_MONTH_WINDOW

        if enabled:
            logger.info(
                "CostQuotaMiddleware initialized with default plan: %s", default_plan
            )
            from backend.telemetry.cost_recording import register_cost_recorder

            register_cost_recorder(self.record_cost)

    # ------------------------------------------------------------------
    # ASGI entry point
    # ------------------------------------------------------------------

    async def __call__(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with cost quota enforcement."""
        if not self._should_enforce_quota(request):
            return await call_next(request)

        quota_key = await self._get_quota_key(request)
        user_plan = await self._get_user_plan(request)

        if not await self._check_quota(quota_key, user_plan):
            logger.warning(
                "Cost quota exceeded for %s (plan: %s)", quota_key, user_plan
            )
            return await self._quota_exceeded_response(quota_key, user_plan)

        response = await call_next(request)
        await self._annotate_response_with_quota(response, quota_key, user_plan)
        return response

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _should_enforce_quota(self, request: Request) -> bool:
        if not self.enabled:
            return False

        path = request.url.path
        if path in QUOTA_EXEMPT_PATHS:
            return False
        for prefix in QUOTA_EXEMPT_PATH_PREFIXES:
            if path.startswith(prefix):
                return False
        return True

    async def _annotate_response_with_quota(
        self,
        response: Response,
        quota_key: str,
        plan: QuotaPlan,
    ) -> None:
        remaining = await self._get_remaining_quota(quota_key, plan)
        config = QUOTA_CONFIGS[plan]
        response.headers["X-Cost-Quota-Plan"] = plan.value
        response.headers["X-Cost-Quota-Daily-Limit"] = str(config.daily_limit)
        response.headers["X-Cost-Quota-Daily-Remaining"] = str(remaining["daily"])
        response.headers["X-Cost-Quota-Monthly-Limit"] = str(config.monthly_limit)
        response.headers["X-Cost-Quota-Monthly-Remaining"] = str(remaining["monthly"])

    async def _get_quota_key(self, request: Request) -> str:
        """Get quota key from request (user_id or hashed IP)."""
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"

        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        try:
            import hashlib

            hashed = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:12]
            return "ip:" + hashed
        except Exception:
            return "ip:unknown"

    async def _get_user_plan(self, request: Request) -> QuotaPlan:
        """Get user's quota plan from request state or default."""
        plan = getattr(request.state, "quota_plan", None)
        if plan:
            try:
                return QuotaPlan(plan)
            except ValueError:
                pass
        return self.default_plan

    # ------------------------------------------------------------------
    # Quota logic
    # ------------------------------------------------------------------

    async def _check_quota(self, key: str, plan: QuotaPlan) -> bool:
        """Check if user is within cost quota."""
        current_time = time.time()
        config = QUOTA_CONFIGS[plan]
        cost_data = _cost_store[key]

        self._reset_cost_windows(cost_data, current_time)
        return self._within_limits(cost_data, config)

    def _reset_cost_windows(
        self, cost_data: dict[str, float], current_time: float
    ) -> None:
        if current_time - cost_data["last_reset_day"] > self.day_window:
            cost_data["daily_cost"] = 0.0
            cost_data["last_reset_day"] = current_time

        if current_time - cost_data["last_reset_month"] > self.month_window:
            cost_data["monthly_cost"] = 0.0
            cost_data["last_reset_month"] = current_time

    def _within_limits(self, cost_data: dict[str, float], config: QuotaConfig) -> bool:
        if cost_data["daily_cost"] >= config.daily_limit:
            logger.debug(
                "Daily quota exceeded: %.2f >= %s",
                cost_data["daily_cost"],
                config.daily_limit,
            )
            return False

        if cost_data["monthly_cost"] >= config.monthly_limit:
            logger.debug(
                "Monthly quota exceeded: %.2f >= %s",
                cost_data["monthly_cost"],
                config.monthly_limit,
            )
            return False
        return True

    async def _get_remaining_quota(self, key: str, plan: QuotaPlan) -> dict[str, float]:
        """Get remaining quota for user."""
        config = QUOTA_CONFIGS[plan]
        cost_data = _cost_store[key]

        return {
            "daily": max(0.0, config.daily_limit - cost_data["daily_cost"]),
            "monthly": max(0.0, config.monthly_limit - cost_data["monthly_cost"]),
        }

    async def _quota_exceeded_response(self, key: str, plan: QuotaPlan) -> JSONResponse:
        """Generate 429 quota exceeded response."""
        from backend.server.utils.error_formatter import format_quota_exceeded_error

        config = QUOTA_CONFIGS[plan]
        cost_data = _cost_store[key]

        if cost_data["daily_cost"] >= config.daily_limit:
            limit_type = "daily"
            limit = config.daily_limit
            spent = cost_data["daily_cost"]
            reset_time = int(cost_data["last_reset_day"] + self.day_window)
        else:
            limit_type = "monthly"
            limit = config.monthly_limit
            spent = cost_data["monthly_cost"]
            reset_time = int(cost_data["last_reset_month"] + self.month_window)

        quota_info = {
            "quota_plan": plan.value,
            "limit_type": limit_type,
            "limit": limit,
            "spent": spent,
            "reset_at": reset_time,
        }
        user_error = format_quota_exceeded_error(quota_info)
        payload = user_error.to_dict()

        resp = JSONResponse(status_code=429, content=payload)
        resp.headers["Retry-After"] = str(reset_time - int(time.time()))
        resp.headers["X-Cost-Quota-Plan"] = plan.value
        return resp

    # ------------------------------------------------------------------
    # Cost recording
    # ------------------------------------------------------------------

    def record_cost(self, key: str, cost: float) -> None:
        """Record cost for a user (in-memory)."""
        if not self.enabled:
            return

        cost_data = _cost_store[key]
        cost_data["daily_cost"] += cost
        cost_data["monthly_cost"] += cost

        logger.debug(
            "Recorded $%.4f for %s. Daily: $%.2f, Monthly: $%.2f",
            cost,
            key,
            cost_data["daily_cost"],
            cost_data["monthly_cost"],
        )
