import contextlib
import importlib.util
import os
import random
import shutil
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.routing import Mount
from starlette.middleware.base import BaseHTTPMiddleware

from backend import __version__
from backend.core.logger import forge_logger as logger
from backend.core.logger import get_trace_context
from backend.core.tracing import initialize_tracing
from backend.api.error_handlers import register_exception_handlers
from backend.api.middleware import (
    LocalhostCORSMiddleware,
    RequestMetricsMiddleware,
    RequestSizeLimiter,
    RequestTimeoutMiddleware,
)
from backend.api.middleware.compression import CompressionMiddleware
from backend.api.middleware.cost_quota import CostQuotaMiddleware
from backend.api.middleware.redis_cost_quota import RedisCostQuotaMiddleware
from backend.api.middleware.observability import RequestObservabilityMiddleware
from backend.api.middleware.rate_limiter import (
    REDIS_AVAILABLE,
    EndpointRateLimiter,
    RedisRateLimiter,
)
from backend.api.middleware.request_id import RequestIDMiddleware
from backend.api.middleware.request_tracing import RequestTracingMiddleware
from backend.api.middleware.resource_quota import ResourceQuotaMiddleware
from backend.api.middleware.security_headers import (
    CSRFProtection,
    SecurityHeadersMiddleware,
)
from backend.api.middleware.audit_logger import AuditLoggerMiddleware
from backend.api.route_registry import register_routes
from backend.api.routes.mcp import mcp_server
from backend.api.shared import config as _forge_config
from backend.api.shared import (
    get_conversation_manager,
)
from backend.api.versioning import version_middleware
from backend.api.otel_config import (
    OTEL_ENABLED as _otel_enabled,
    get_effective_http_sample,
)

mcp_app = mcp_server.http_app(path="/mcp", stateless_http=True)


def combine_lifespans(*lifespans):
    """Combine multiple FastAPI lifespan functions into a single lifespan.

    Args:
        *lifespans: Variable number of lifespan functions to combine.

    Returns:
        Combined lifespan function that runs all provided lifespans.

    """

    @contextlib.asynccontextmanager
    async def combined_lifespan(fastapi_app):
        """Execute each provided lifespan sequentially within a single ExitStack."""
        async with contextlib.AsyncExitStack() as stack:
            optional_startup_timeout = float(
                os.getenv("FORGE_OPTIONAL_LIFESPAN_TIMEOUT_SEC", "20")
            )
            for index, lifespan in enumerate(lifespans):
                lifespan_name = getattr(lifespan, "__name__", str(lifespan))
                # First lifespan is core app startup and should fail fast if broken.
                if index == 0:
                    await stack.enter_async_context(lifespan(fastapi_app))
                    continue

                # Additional lifespans (e.g., optional integrations) should not
                # block the entire API startup indefinitely.
                try:
                    await asyncio.wait_for(
                        stack.enter_async_context(lifespan(fastapi_app)),
                        timeout=optional_startup_timeout,
                    )
                except TimeoutError:
                    logger.warning(
                        "Optional lifespan '%s' timed out after %.1fs; continuing startup.",
                        lifespan_name,
                        optional_startup_timeout,
                    )
                except Exception as exc:
                    logger.warning(
                        "Optional lifespan '%s' failed during startup (%s); continuing.",
                        lifespan_name,
                        exc,
                    )
            yield

    return combined_lifespan


def _validate_config() -> None:
    """Validate essential configuration at startup — warn loudly on misconfig.

    This runs once during the lifespan startup phase and logs warnings for
    common misconfigurations that silently degrade the experience.

    Set ``FORGE_STRICT=1`` (or ``FORGE_ENV=production``) to promote warnings
    to hard errors that prevent startup.
    """
    strict = (
        os.getenv("FORGE_STRICT", "").strip().lower() in ("1", "true", "yes")
        or os.getenv("FORGE_ENV", "").strip().lower() == "production"
    )

    validation_warnings, errors = _collect_validation_issues(strict)

    if errors:
        logger.error("=" * 60)
        logger.error("FATAL CONFIG ERRORS (strict mode)")
        logger.error("=" * 60)
        for e in errors:
            logger.error("  %s", e)
        logger.error("=" * 60)
        raise SystemExit(
            "Forge cannot start due to configuration errors. "
            "Fix the issues above or unset FORGE_STRICT / FORGE_ENV=production."
        )

    if validation_warnings:
        logger.warning("=" * 60)
        logger.warning("STARTUP CONFIG WARNINGS")
        logger.warning("=" * 60)
        for w in validation_warnings:
            logger.warning("  %s", w)
        logger.warning("=" * 60)
        if strict:
            raise SystemExit(
                "Forge strict mode: resolve all warnings above or unset FORGE_STRICT."
            )
    else:
        logger.info("Config validation passed.")


def _collect_validation_issues(strict: bool) -> tuple[list[str], list[str]]:
    """Split config validation into modular checks."""
    warnings: list[str] = []
    errors: list[str] = []

    _check_budget_sanity(warnings)
    _check_database_availability(warnings)
    _check_system_dependencies(warnings)
    _check_config_file_existence(warnings)
    _check_mcp_host_config(warnings)

    return warnings, errors


def _check_budget_sanity(warnings: list[str]) -> None:
    """Warn on unlimited task budget."""
    budget = getattr(_forge_config, "max_budget_per_task", None)
    if budget is None or budget == 0 or budget == 0.0:
        warnings.append(
            "max_budget_per_task is unlimited (None / 0). Long sessions with "
            "expensive models can accumulate significant costs. "
            "Set max_budget_per_task in settings.json (default: $5.00)."
        )


def _check_database_availability(warnings: list[str]) -> None:
    """Check database storage dependencies."""
    if os.getenv("KB_STORAGE_TYPE", "file").lower() in ("database", "db"):
        if importlib.util.find_spec("asyncpg") is None:
            warnings.append(
                "KB_STORAGE_TYPE=database but 'asyncpg' is not installed. Install with: pip install asyncpg"
            )
        if not os.getenv("DATABASE_URL"):
            warnings.append("KB_STORAGE_TYPE=database but DATABASE_URL is not set.")


def _check_system_dependencies(warnings: list[str]) -> None:
    """Check required system tools like tmux."""
    if not shutil.which("tmux"):
        warnings.append(
            "tmux is not installed or not on PATH. Some agent terminal features may not work."
        )


def _check_config_file_existence(warnings: list[str]) -> None:
    """Check for settings.json."""
    from pathlib import Path

    if not Path("settings.json").exists():
        warnings.append(
            "No settings.json found. Copy settings.template.json → settings.json and set your LLM API key."
        )

def _check_mcp_host_config(warnings: list[str]) -> None:
    """Warn on missing mcp_host configuration."""
    mcp_host = getattr(_forge_config, "mcp_host", None)
    if not mcp_host:
        warnings.append(
            "mcp_host is not set in settings.json. The internal Forge MCP server "
            "will be disabled. AI agents will not have access to built-in "
            "workspace tools like search and file reading. Set mcp_host=\"localhost:8000\" "
            "(or your server's host:port) to enable internal tools."
        )

@asynccontextmanager
async def _lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    """Manage application-specific resources during startup/shutdown."""
    # ── Config validation (fail fast on misconfiguration) ───────────────
    # Reload config to ensure it picks up any changes made to settings.json
    from backend.core.config.utils import load_forge_config
    fastapi_app.state.config = load_forge_config()
    
    _validate_config()

    # Startup
    logger.info("Starting Forge server...")

    # Initialize Sentry error tracking (if configured)
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

            sentry_sdk.init(
                dsn=sentry_dsn,
                environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
                release=os.getenv("SENTRY_RELEASE", __version__),
                traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
                sample_rate=float(os.getenv("SENTRY_SAMPLE_RATE", "1.0")),
                integrations=[
                    FastApiIntegration(),
                    SqlalchemyIntegration(),
                ],
            )
            logger.info("Sentry error tracking initialized")
        except ImportError:
            logger.warning(
                "sentry-sdk not installed. Install with: pip install sentry-sdk"
            )
        except Exception as e:
            logger.warning("Sentry initialization failed: %s", e)

    # Initialize database schemas if storage type is set to database
    if os.getenv("KB_STORAGE_TYPE", "file").lower() in ("database", "db"):
        logger.info("Initializing database schemas...")
        try:
            from backend.storage.conversation.database_conversation_store import (
                DatabaseConversationStore,
            )
            from backend.storage.db_pool import get_db_pool
            from backend.storage.knowledge_base.database_knowledge_base_store import (
                DatabaseKnowledgeBaseStore,
            )

            pool = await get_db_pool()

            # Init Knowledge Base
            kb_store = DatabaseKnowledgeBaseStore(pool=pool)
            await kb_store.initialize()

            # Init Conversations & Audit
            conv_store = DatabaseConversationStore(pool=pool)
            await conv_store.initialize()

            logger.info("Database schemas initialized successfully.")
        except Exception as e:
            logger.error("Schema initialization failed: %s", e, exc_info=True)

    # Register shutdown handlers for graceful shutdown
    from backend.api.graceful_shutdown import register_shutdown_handler

    async def cleanup_conversations():
        """Cleanup all active conversations on shutdown."""
        try:
            async with get_conversation_manager() as manager:
                running_sids = await manager.get_running_agent_loops()
                logger.info("Stopping %d active conversations...", len(running_sids))
                for sid in running_sids:
                    try:
                        await manager.close_session(sid)
                    except Exception as e:
                        logger.error(
                            "Error stopping conversation %s: %s", sid, e, exc_info=True
                        )
        except Exception as e:
            logger.error("Error during conversation cleanup: %s", e, exc_info=True)

    async def cleanup_socketio():
        """Close Socket.IO connections gracefully."""
        try:
            from backend.api.shared import sio

            logger.info("Closing Socket.IO connections...")
            await sio.shutdown()
        except Exception as e:
            logger.error("Error closing Socket.IO: %s", e, exc_info=True)

    register_shutdown_handler(cleanup_conversations)
    register_shutdown_handler(cleanup_socketio)

    # Lazily initialize the conversation manager to avoid None during import time
    async with get_conversation_manager():
        logger.info("Forge server started successfully")
        yield
        # Shutdown
        logger.info("Shutting down Forge server...")
        from backend.api.graceful_shutdown import graceful_shutdown

        await graceful_shutdown()


app = FastAPI(
    title="Forge API",
    description=(
        "Forge: Production-grade AI development platform\n\n"
        "Features:\n"
        "- Structure-aware code editing\n"
        "- Real-time collaboration\n"
        "- Enterprise security & monitoring\n\n"
        "Documentation: https://docs.forge.ai\n"
        "Support: support@forge.ai"
    ),
    version=__version__,
    lifespan=combine_lifespans(_lifespan, mcp_app.lifespan),
    routes=[Mount(path="/mcp", app=mcp_app)],
    # OpenAPI configuration
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc alternative
    openapi_url="/openapi.json",  # OpenAPI spec
    openapi_tags=[
        {"name": "v1", "description": "Stable API - Version 1 (current)"},
        {"name": "conversations", "description": "Conversation management endpoints"},
        {"name": "files", "description": "File operations and workspace management"},
        {"name": "settings", "description": "User settings and configuration"},
        {"name": "monitoring", "description": "Metrics and system health"},
    ],
)

# Add security and performance middleware
# Order matters: CORS -> auth -> versioning -> compression -> security headers
# -> CSRF -> rate limiting -> resource quotas

# 0. CORS (should be first to handle cross-origin requests)
# 🔒 SECURITY: Use LocalhostCORSMiddleware which always allows localhost/127.0.0.1
# while still respecting configured origins for production

app.add_middleware(LocalhostCORSMiddleware)

# 0.5. Request ID (add unique request IDs for tracing)

app.add_middleware(RequestIDMiddleware)

# 0.6. Request Tracing (add request IDs for debugging)

app.add_middleware(BaseHTTPMiddleware, dispatch=RequestTracingMiddleware(enabled=True))

# 0.7. Audit Logging (log sensitive operations for security audit)

app.add_middleware(AuditLoggerMiddleware)

# Initialize distributed tracing (opt-in — requires `telemetry` extras)
_tracing_enabled = os.getenv(
    "TRACING_ENABLED", os.getenv("OTEL_ENABLED", "false")
).lower() in (
    "true",
    "1",
    "yes",
)
if _tracing_enabled:
    try:
        _tracing_sample_rate = float(
            os.getenv("TRACING_SAMPLE_RATE", os.getenv("OTEL_SAMPLE_DEFAULT", "0.1"))
        )
    except Exception:
        _tracing_sample_rate = 0.1
    initialize_tracing(
        service_name=os.getenv(
            "TRACING_SERVICE_NAME", os.getenv("SERVICE_NAME", "forge-server")
        ),
        service_version=os.getenv("TRACING_SERVICE_VERSION", __version__),
        exporter=os.getenv("TRACING_EXPORTER", os.getenv("OTEL_EXPORTER", "console")),
        endpoint=os.getenv("TRACING_ENDPOINT", os.getenv("OTEL_EXPORTER_ENDPOINT")),
        sample_rate=_tracing_sample_rate,
        enabled=True,
    )

if _otel_enabled:
    try:  # pragma: no cover - optional instrumentation
        from opentelemetry import trace
        from opentelemetry.trace import SpanKind

        tracer = trace.get_tracer("forge.server")

        async def otel_wrapper(request: Request, call_next):
            request_path = request.url.path
            route_path = getattr(
                getattr(request.scope.get("route", None), "path", None),
                "__str__",
                lambda: None,
            )()
            if not route_path:
                route_path = request_path

            # Determine effective sample rate using helper (regex > simple > base).
            # Use the concrete request path so overrides work even on 404s where
            # the resolved route path may be a generic mount/template.
            effective_rate = get_effective_http_sample(request_path)
            # Head sampling: skip span creation if random() > effective_rate
            if random.random() >= effective_rate:
                return await call_next(request)
            with tracer.start_as_current_span(
                name=f"HTTP {request.method} {request_path}",
                kind=SpanKind.SERVER,
            ) as span:
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.route", route_path)
                span.set_attribute("http.target", request_path)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute(
                    "forge.request_id",
                    getattr(getattr(request, "state", object()), "request_id", ""),
                )
                # Bridge thread-local orchestrator trace_id for correlation
                try:
                    ctx = get_trace_context()
                    tid = ctx.get("trace_id") if isinstance(ctx, dict) else None
                    if tid:
                        span.set_attribute("forge.trace_id", str(tid))
                except Exception:
                    logger.debug("Failed to bridge OTEL trace context", exc_info=True)
                try:
                    response = await call_next(request)
                    span.set_attribute("http.status_code", response.status_code)
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("error", True)
                    raise
                return response

        app.add_middleware(BaseHTTPMiddleware, dispatch=otel_wrapper)
    except Exception as e:  # pragma: no cover
        logger.warning("OTEL instrumentation initialization failed: %s", e)

# 0.6. API Versioning (after request tracing, before other middleware)

app.add_middleware(BaseHTTPMiddleware, dispatch=version_middleware)

# 0.65. Request Metrics (opt-in — lightweight Prometheus-friendly counters/histogram)
metrics_enabled = os.getenv("REQUEST_METRICS_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
if metrics_enabled:
    app.add_middleware(
        BaseHTTPMiddleware, dispatch=RequestMetricsMiddleware(enabled=True)
    )

# Request size limiting (prevent DoS via large request bodies)
request_size_limit_enabled = (
    os.getenv("REQUEST_SIZE_LIMIT_ENABLED", "true").lower() == "true"
)
app.add_middleware(
    RequestSizeLimiter,
    enabled=request_size_limit_enabled,
    # No more E402 here!
)

# Request timeout protection (prevent resource exhaustion from hanging requests)
request_timeout_enabled = os.getenv("REQUEST_TIMEOUT_ENABLED", "true").lower() == "true"
app.add_middleware(
    RequestTimeoutMiddleware,
    enabled=request_timeout_enabled,
)

# 1. Compression (should be first to compress all responses)
app.add_middleware(
    BaseHTTPMiddleware,
    dispatch=CompressionMiddleware(min_compress_size=1024),
)

# 2. Security headers
# CSP policy can be toggled via env: CSP_POLICY=permissive|strict
# Default: strict in production-like environments, permissive otherwise
env_hint = (
    os.getenv("FORGE_ENV")
    or os.getenv("ENV")
    or os.getenv("PYTHON_ENV")
    or os.getenv("NODE_ENV")
    or "development"
).lower()
default_csp = (
    "strict" if any(x in env_hint for x in ("prod", "production")) else "permissive"
)
csp_policy = os.getenv("CSP_POLICY", default_csp).lower()
if csp_policy not in ("permissive", "strict"):
    csp_policy = default_csp
app.add_middleware(
    BaseHTTPMiddleware,
    dispatch=SecurityHeadersMiddleware(enabled=True, csp_profile=csp_policy),
)

# 3. CSRF protection (opt-in via CSRF_PROTECTION_ENABLED=true)
csrf_enabled = os.getenv("CSRF_PROTECTION_ENABLED", "false").lower() == "true"
if csrf_enabled:
    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=CSRFProtection(enabled=True),
    )

# 4. Resource Quotas (before rate limiting to check quotas first)
resource_quota_enabled = os.getenv("RESOURCE_QUOTA_ENABLED", "false").lower() == "true"
if resource_quota_enabled:
    app.add_middleware(ResourceQuotaMiddleware, enabled=True)
    logger.info("Resource quota middleware enabled")

# 4.5. Rate limiting & Cost quotas
# Use Redis-backed rate limiter if REDIS_URL or REDIS_HOST is configured, otherwise in-memory
rate_limiter_enabled = os.getenv("RATE_LIMITING_ENABLED", "false").lower() == "true"
cost_quota_enabled = os.getenv("COST_QUOTA_ENABLED", "false").lower() == "true"

# Auto-detect Redis URL from environment (REDIS_URL takes precedence over REDIS_HOST)
redis_url = os.getenv("REDIS_URL")
if not redis_url and os.getenv("REDIS_HOST"):
    redis_url = f"redis://{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT', '6379')}"
    if redis_password := os.getenv("REDIS_PASSWORD"):
        redis_url = f"redis://:{redis_password}@{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT', '6379')}"

# Use Redis if available, otherwise fall back to in-memory
if REDIS_AVAILABLE and redis_url:
    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=RedisRateLimiter(
            redis_url=redis_url,
            enabled=rate_limiter_enabled,
        ),
    )
    # Add Redis-backed cost quota middleware with connection pooling and health checks
    if cost_quota_enabled:
        logger.info("Using Redis cost quota middleware with connection pooling")
        connection_pool_size = int(os.getenv("REDIS_POOL_SIZE", "10"))
        connection_timeout = float(os.getenv("REDIS_TIMEOUT", "5.0"))
        fallback_enabled = os.getenv("REDIS_QUOTA_FALLBACK", "true").lower() == "true"
        app.add_middleware(
            BaseHTTPMiddleware,
            dispatch=RedisCostQuotaMiddleware(
                redis_url=redis_url,
                enabled=True,
                connection_pool_size=connection_pool_size,
                connection_timeout=connection_timeout,
                fallback_enabled=fallback_enabled,
            ),
        )
else:
    app.add_middleware(
        BaseHTTPMiddleware,
        dispatch=EndpointRateLimiter(enabled=rate_limiter_enabled),
    )
    # Add in-memory cost quota middleware with graceful fallback message
    if cost_quota_enabled:
        logger.info(
            "Using in-memory cost quota middleware (Redis not available). "
            "Set REDIS_URL to enable distributed quota tracking."
        )
        app.add_middleware(
            BaseHTTPMiddleware,
            dispatch=CostQuotaMiddleware(
                enabled=True,
            ),
        )

# 5. Observability middleware (opt-in — SLO tracking, alerting)
observability_enabled = os.getenv("OBSERVABILITY_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
alerting_enabled = os.getenv("ALERTING_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
if observability_enabled:
    app.add_middleware(
        RequestObservabilityMiddleware,
        alerting_enabled=alerting_enabled,
    )

register_exception_handlers(app)
register_routes(app)
