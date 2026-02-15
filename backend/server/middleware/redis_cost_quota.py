"""Redis-backed cost quota middleware for distributed systems.

Extends the in-memory CostQuotaMiddleware with Redis persistence,
connection pooling, health checks, and OpenTelemetry instrumentation.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import TYPE_CHECKING

from backend.core.enums import QuotaPlan
from backend.core.logger import FORGE_logger as logger
from backend.core.logger import get_trace_context
from backend.server.middleware.cost_quota import (
    QUOTA_CONFIGS,
    CostQuotaMiddleware,
    QuotaConfig,
    RedisQuotaKeys,
)

if TYPE_CHECKING:
    import redis.asyncio as redis


# Redis availability detection
try:
    import redis.asyncio as redis  # type: ignore[no-redef]

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("Redis not available, using in-memory cost tracking")


class RedisCostQuotaMiddleware(CostQuotaMiddleware):
    """Redis-backed cost quota for distributed systems with connection pooling and health checks."""

    @staticmethod
    def _redis_keys(key: str) -> RedisQuotaKeys:
        prefix = "cost_quota"
        return RedisQuotaKeys(
            daily=f"{prefix}:daily:{key}",
            monthly=f"{prefix}:monthly:{key}",
            daily_reset=f"{prefix}:daily_reset:{key}",
            monthly_reset=f"{prefix}:monthly_reset:{key}",
        )

    def __init__(
        self,
        redis_url: str | None = None,
        enabled: bool = True,
        default_plan: QuotaPlan = QuotaPlan.FREE,
        connection_pool_size: int = 10,
        connection_timeout: float = 5.0,
        fallback_enabled: bool = True,
    ) -> None:
        """Initialize Redis cost quota middleware.

        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var)
            enabled: Whether cost quota enforcement is enabled
            default_plan: Default plan for users
            connection_pool_size: Redis connection pool size
            connection_timeout: Redis connection timeout in seconds
            fallback_enabled: Fall back to in-memory if Redis unavailable

        """
        super().__init__(enabled, default_plan)
        env_url = os.getenv("REDIS_URL")
        self.redis_url: str = redis_url or env_url or "redis://localhost:6379"
        self.connection_pool_size = connection_pool_size
        self.connection_timeout = connection_timeout
        self.fallback_enabled = fallback_enabled
        self._redis_client: redis.Redis | None = None
        self._redis_pool: redis.ConnectionPool | None = None
        self._redis_health_check_interval = 60.0
        self._last_health_check = 0.0
        self._redis_healthy = False

        if enabled:
            logger.info(
                "RedisCostQuotaMiddleware initialized with default plan: %s, "
                "redis_url: %s, pool_size: %s",
                default_plan,
                self.redis_url,
                connection_pool_size,
            )

    # ------------------------------------------------------------------
    # Redis client lifecycle
    # ------------------------------------------------------------------

    async def _get_redis_client(self) -> redis.Redis | None:
        """Get or create Redis client with connection pooling and health checks."""
        if not self._is_redis_enabled():
            return None

        current_time = time.time()
        await self._health_check_existing_client(current_time)

        if self._redis_client is None:
            await self._establish_new_client(current_time)

        if self._redis_client is None and not self.fallback_enabled:
            logger.error(
                "Redis unavailable and fallback disabled. Quota tracking disabled."
            )
            return None

        return self._redis_client

    def _is_redis_enabled(self) -> bool:
        if REDIS_AVAILABLE:
            return True
        if self.fallback_enabled:
            logger.debug("Redis not available, using in-memory quota tracking")
        return False

    async def _health_check_existing_client(self, current_time: float) -> None:
        if (
            self._redis_client is None
            or current_time - self._last_health_check
            <= self._redis_health_check_interval
        ):
            return

        try:
            await self._redis_client.ping()
            self._redis_healthy = True
            self._last_health_check = current_time
        except Exception as exc:
            logger.warning("Redis health check failed: %s. Reconnecting...", exc)
            self._redis_healthy = False
            self._redis_client = None
            self._redis_pool = None

    async def _establish_new_client(self, current_time: float) -> None:
        try:
            self._redis_client = await self._create_redis_client()
            await asyncio.wait_for(
                self._redis_client.ping(), timeout=self.connection_timeout
            )
            self._redis_healthy = True
            self._last_health_check = current_time
            logger.info(
                "Connected to Redis for cost quota tracking (pool_size: %s)",
                self.connection_pool_size,
            )
        except TimeoutError:
            logger.warning(
                "Redis connection timeout after %ss. %s",
                self.connection_timeout,
                "Falling back to in-memory."
                if self.fallback_enabled
                else "Quota tracking disabled.",
            )
            self._redis_client = None
            self._redis_pool = None
            self._redis_healthy = False
        except Exception as exc:
            logger.warning(
                "Failed to connect to Redis: %s. %s",
                exc,
                "Falling back to in-memory."
                if self.fallback_enabled
                else "Quota tracking disabled.",
            )
            self._redis_client = None
            self._redis_pool = None
            self._redis_healthy = False

    async def _create_redis_client(self) -> redis.Redis:
        """Create a Redis client using either a connection pool or from_url fallback."""
        connection_pool_cls = getattr(redis, "ConnectionPool", None)
        if connection_pool_cls and hasattr(connection_pool_cls, "from_url"):
            self._redis_pool = connection_pool_cls.from_url(
                self.redis_url,
                max_connections=self.connection_pool_size,
                decode_responses=True,
                socket_connect_timeout=self.connection_timeout,
                socket_timeout=self.connection_timeout,
                retry_on_timeout=True,
                health_check_interval=30,
            )
            return redis.Redis(connection_pool=self._redis_pool)

        from_url = getattr(redis, "from_url", None)
        if callable(from_url):
            return from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=self.connection_timeout,
                socket_timeout=self.connection_timeout,
            )

        raise RuntimeError(
            "Redis module is missing ConnectionPool.from_url and from_url."
        )

    # ------------------------------------------------------------------
    # Quota checking
    # ------------------------------------------------------------------

    async def _window_cost(
        self,
        redis_client: redis.Redis,
        value_key: str,
        reset_key: str,
        window: float,
        current_time: float,
    ) -> float:
        reset_time = await redis_client.get(reset_key)
        if not self._redis_client_supports_mutation(redis_client):
            return float(await redis_client.get(value_key) or 0.0)

        if reset_time is None or current_time - float(reset_time) > window:
            await redis_client.set(value_key, "0.0")
            await redis_client.set(reset_key, str(current_time))
            await redis_client.expire(value_key, int(window))
            await redis_client.expire(reset_key, int(window))
            return 0.0
        return float(await redis_client.get(value_key) or 0.0)

    @staticmethod
    def _redis_client_supports_mutation(redis_client: redis.Redis) -> bool:
        return all(hasattr(redis_client, attr) for attr in ("set", "expire"))

    def _apply_limit_checks(
        self,
        key: str,
        config: QuotaConfig,
        daily_cost: float,
        monthly_cost: float,
    ) -> bool:
        allowed = True
        if daily_cost >= config.daily_limit:
            allowed = False
            logger.debug(
                "Daily quota exceeded for %s: $%.2f >= $%s",
                key,
                daily_cost,
                config.daily_limit,
            )
        if monthly_cost >= config.monthly_limit:
            allowed = False
            logger.debug(
                "Monthly quota exceeded for %s: $%.2f >= $%s",
                key,
                monthly_cost,
                config.monthly_limit,
            )
        return allowed

    async def _check_quota(self, key: str, plan: QuotaPlan) -> bool:
        """Check quota using Redis."""
        redis_client = await self._get_redis_client()

        if redis_client is None:
            return await super()._check_quota(key, plan)

        try:
            current_time = time.time()
            config = QUOTA_CONFIGS[plan]
            redis_keys = self._redis_keys(key)

            daily_cost = await self._window_cost(
                redis_client,
                redis_keys.daily,
                redis_keys.daily_reset,
                self.day_window,
                current_time,
            )
            monthly_cost = await self._window_cost(
                redis_client,
                redis_keys.monthly,
                redis_keys.monthly_reset,
                self.month_window,
                current_time,
            )

            allowed = self._apply_limit_checks(key, config, daily_cost, monthly_cost)

            if self._should_instrument_redis():
                self._record_quota_span(
                    key, plan, config, daily_cost, monthly_cost, allowed
                )

            return allowed

        except Exception as exc:
            return await self._handle_redis_check_failure(exc, key, plan)

    async def _get_remaining_quota(self, key: str, plan: QuotaPlan) -> dict[str, float]:
        """Get remaining quota using Redis."""
        redis_client = await self._get_redis_client()

        if redis_client is None:
            return await super()._get_remaining_quota(key, plan)

        try:
            current_time = time.time()
            config = QUOTA_CONFIGS[plan]
            redis_keys = self._redis_keys(key)

            daily_cost = await self._window_cost(
                redis_client,
                redis_keys.daily,
                redis_keys.daily_reset,
                self.day_window,
                current_time,
            )
            monthly_cost = await self._window_cost(
                redis_client,
                redis_keys.monthly,
                redis_keys.monthly_reset,
                self.month_window,
                current_time,
            )

            return {
                "daily": max(0.0, config.daily_limit - daily_cost),
                "monthly": max(0.0, config.monthly_limit - monthly_cost),
            }

        except Exception as e:
            logger.error(
                "Redis remaining quota check failed: %s. Falling back to in-memory.", e
            )
            return await super()._get_remaining_quota(key, plan)

    # ------------------------------------------------------------------
    # Cost recording
    # ------------------------------------------------------------------

    def record_cost(self, key: str, cost: float) -> None:
        """Record cost (sync fallback to in-memory)."""
        if not self.enabled:
            return
        super().record_cost(key, cost)

    async def record_cost_async(self, key: str, cost: float) -> None:
        """Record cost using Redis (async version)."""
        if not self.enabled:
            return

        redis_client = await self._get_redis_client()
        if redis_client is None:
            super().record_cost(key, cost)
            return

        try:
            current_time = time.time()
            keys = self._redis_keys(key)
            await self._ensure_reset_keys(redis_client, keys, current_time)
            await self._increment_cost_buckets(redis_client, keys, cost)
            self._maybe_instrument_cost_record(key, cost)
        except Exception as exc:
            logger.error("Failed to record cost in Redis: %s", exc)
            if self.fallback_enabled:
                super().record_cost(key, cost)
            else:
                logger.warning(
                    "Redis unavailable and fallback disabled. Cost not recorded for %s",
                    key,
                )

    async def _ensure_reset_keys(
        self,
        redis_client: redis.Redis,
        keys: RedisQuotaKeys,
        current_time: float,
    ) -> None:
        if not self._redis_client_supports_mutation(redis_client):
            return

        await self._initialize_reset_key(
            redis_client, keys.daily_reset, keys.daily, self.day_window, current_time
        )
        await self._initialize_reset_key(
            redis_client,
            keys.monthly_reset,
            keys.monthly,
            self.month_window,
            current_time,
        )

    async def _initialize_reset_key(
        self,
        redis_client: redis.Redis,
        reset_key: str,
        value_key: str,
        window: float,
        current_time: float,
    ) -> None:
        reset_time = await redis_client.get(reset_key)
        if reset_time is not None:
            return

        await redis_client.set(reset_key, str(current_time))
        if hasattr(redis_client, "expire"):
            await redis_client.expire(reset_key, int(window))
            await redis_client.set(value_key, "0.0")
            await redis_client.expire(value_key, int(window))

    async def _increment_cost_buckets(
        self,
        redis_client: redis.Redis,
        keys: RedisQuotaKeys,
        cost: float,
    ) -> None:
        await redis_client.incrbyfloat(keys.daily, cost)
        await redis_client.incrbyfloat(keys.monthly, cost)
        if hasattr(redis_client, "expire"):
            await redis_client.expire(keys.daily, self.day_window)
            await redis_client.expire(keys.monthly, self.month_window)

    # ------------------------------------------------------------------
    # Observability helpers
    # ------------------------------------------------------------------

    def _should_instrument_redis(self) -> bool:
        enabled_value = os.getenv("OTEL_INSTRUMENT_REDIS")
        if enabled_value is None:
            enabled_value = os.getenv("OTEL_ENABLED", "false")
        if enabled_value.lower() not in ("true", "1", "yes"):
            return False

        sample_str = os.getenv(
            "OTEL_SAMPLE_REDIS",
            os.getenv("OTEL_SAMPLE_DEFAULT", "1.0"),
        )
        try:
            sample_rate = max(0.0, min(1.0, float(sample_str)))
        except Exception:
            sample_rate = 1.0
        return random.random() < sample_rate  # noqa: S311

    def _record_quota_span(
        self,
        key: str,
        plan: QuotaPlan,
        config: QuotaConfig,
        daily_cost: float,
        monthly_cost: float,
        allowed: bool,
    ) -> None:
        try:
            from opentelemetry import trace as _otel_trace  # type: ignore[import-untyped]
            from opentelemetry.trace import SpanKind as _SpanKind  # type: ignore[import-untyped]
        except Exception:
            return

        tracer = _otel_trace.get_tracer("forge.redis")
        with tracer.start_as_current_span("quota.check", kind=_SpanKind.CLIENT) as span:
            span.set_attribute("db.system", "redis")
            span.set_attribute("quota.key", key)
            span.set_attribute("quota.plan", plan.value)
            span.set_attribute("quota.daily.cost", float(daily_cost))
            span.set_attribute("quota.monthly.cost", float(monthly_cost))
            span.set_attribute("quota.daily.limit", float(config.daily_limit))
            span.set_attribute("quota.monthly.limit", float(config.monthly_limit))
            span.set_attribute("quota.allowed", bool(allowed))
            ctx = get_trace_context()
            if ctx.get("trace_id"):
                span.set_attribute("forge.trace_id", str(ctx["trace_id"]))

    async def _handle_redis_check_failure(
        self,
        exc: Exception,
        key: str,
        plan: QuotaPlan,
    ) -> bool:
        logger.error(
            "Redis quota check failed: %s. %s",
            exc,
            "Allowing request (fail-open)."
            if self.fallback_enabled
            else "Blocking request (fail-closed).",
        )
        if self.fallback_enabled:
            return await super()._check_quota(key, plan)
        return False

    def _maybe_instrument_cost_record(self, key: str, cost: float) -> None:
        if not self._should_instrument_redis():
            return

        from backend.utils.otel_utils import redis_span

        with redis_span("quota.record_cost") as span:
            if span is None:
                return
            span.set_attribute("quota.key", key)
            span.set_attribute("quota.cost.usd", float(cost))
