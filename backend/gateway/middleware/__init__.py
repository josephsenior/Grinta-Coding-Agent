"""Server middleware exports.

This package re-exports middleware utilities and classes, including helpers
defined in the sibling module ``app.server.middleware`` (middleware.py).
We import those helpers via an explicit relative import to avoid recursive
package-import issues and circular initialization.
"""

from __future__ import annotations

import logging

from backend.gateway.middleware.cost_quota import CostQuotaMiddleware
from backend.gateway.middleware.cost_recording import record_llm_cost
from backend.gateway.middleware.redis_cost_quota import RedisCostQuotaMiddleware
from backend.gateway.middleware.rate_limiter import (
    REDIS_AVAILABLE,
    EndpointRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)
from backend.gateway.middleware.request_limits import RequestSizeLimiter
from backend.gateway.middleware.request_metrics import RequestMetricsMiddleware
from backend.gateway.middleware.request_size import RequestSizeLoggingMiddleware
from backend.gateway.middleware.security_headers import (
    CSRFProtection,
    SecurityHeadersMiddleware,
)
from backend.gateway.middleware.timeout import RequestTimeoutMiddleware

# Import helpers from the sibling module middleware.py deterministically to
# avoid importing the package name "app.server.middleware" recursively.
from ..middleware_core import (
    CacheControlMiddleware,
    InMemoryRateLimiter,
    LocalhostCORSMiddleware,
    RateLimitMiddleware,
)

logger = logging.getLogger("app.middleware")

__all__ = [
    "CacheControlMiddleware",
    "CostQuotaMiddleware",
    "CSRFProtection",
    "EndpointRateLimiter",
    "InMemoryRateLimiter",
    "LocalhostCORSMiddleware",
    "RequestMetricsMiddleware",
    "RequestSizeLoggingMiddleware",
    "RequestSizeLimiter",
    "RequestTimeoutMiddleware",
    "REDIS_AVAILABLE",
    "RateLimitMiddleware",
    "RateLimiter",
    "RedisCostQuotaMiddleware",
    "RedisRateLimiter",
    "SecurityHeadersMiddleware",
    "record_llm_cost",
]
