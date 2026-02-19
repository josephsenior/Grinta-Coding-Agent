"""Global factory and helpers for cost quota middleware.

Provides ``get_cost_quota_middleware()`` which auto-detects Redis and
returns the appropriate middleware instance, plus a convenience
``record_llm_cost()`` function for recording costs from anywhere.
"""

from __future__ import annotations

import os

from backend.core.logger import forge_logger as logger
from backend.server.middleware.cost_quota import CostQuotaMiddleware

# Redis availability detection (matches redis_cost_quota.py)
try:
    import redis.asyncio as _redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


_GLOBAL_QUOTA_MIDDLEWARE: CostQuotaMiddleware | None = None


def get_cost_quota_middleware() -> CostQuotaMiddleware:
    """Get or create global cost quota middleware instance.

    Auto-detects Redis and uses ``RedisCostQuotaMiddleware`` if available,
    otherwise falls back to in-memory ``CostQuotaMiddleware``.
    """
    global _GLOBAL_QUOTA_MIDDLEWARE
    if _GLOBAL_QUOTA_MIDDLEWARE is not None:
        return _GLOBAL_QUOTA_MIDDLEWARE

    if REDIS_AVAILABLE:
        _GLOBAL_QUOTA_MIDDLEWARE = _try_redis_middleware()

    if _GLOBAL_QUOTA_MIDDLEWARE is None:
        _GLOBAL_QUOTA_MIDDLEWARE = CostQuotaMiddleware(enabled=True)
        logger.info("Using in-memory cost quota middleware (Redis not available)")

    return _GLOBAL_QUOTA_MIDDLEWARE


def _try_redis_middleware() -> CostQuotaMiddleware | None:
    """Attempt to create a Redis-backed middleware, returning *None* on failure."""
    from backend.server.middleware.redis_cost_quota import RedisCostQuotaMiddleware

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        middleware = RedisCostQuotaMiddleware(
            redis_url=redis_url,
            enabled=True,
            connection_pool_size=int(os.getenv("REDIS_POOL_SIZE", "10")),
            connection_timeout=float(os.getenv("REDIS_TIMEOUT", "5.0")),
            fallback_enabled=os.getenv("REDIS_QUOTA_FALLBACK", "true").lower()
            == "true",
        )
        logger.info("Using Redis-backed cost quota middleware")
        return middleware
    except Exception as exc:
        logger.warning(
            "Failed to initialize Redis quota middleware: %s. Falling back to in-memory.",
            exc,
        )
        return None


def record_llm_cost(user_key: str, cost: float) -> None:
    """Record LLM cost for a user.

    Args:
        user_key: User quota key (user:id or ip:address)
        cost: Cost in dollars

    """
    middleware = get_cost_quota_middleware()
    middleware.record_cost(user_key, cost)
