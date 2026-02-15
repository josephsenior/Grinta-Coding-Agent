"""Request Tracing Middleware.

Adds correlation IDs to all requests for end-to-end tracing.

Features:
- Unique request ID per request
- Propagates through logs
- Included in responses
- Performance timing
- Distributed tracing ready
"""

import contextvars
import logging
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response

from backend.core.logger import ACCESS_logger
from backend.core.logger import FORGE_logger as logger


class RequestTracingMiddleware:
    """Middleware that adds request ID and timing to all requests."""

    def __init__(self, enabled: bool = True):
        """Enable or disable request tracing behavior."""
        self.enabled = enabled

    async def __call__(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Add request ID and timing to request."""
        if not self.enabled:
            return await call_next(request)

        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Store request ID in request state for access in route handlers
        request.state.request_id = request_id

        # Store in context variable for logging
        _request_id_ctx_var.set(request_id)

        # Record start time
        start_time = time.time()

        # Log request start (access log channel)
        ACCESS_logger.info(
            "Request started: %s %s",
            request.method,
            request.url.path,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log error with request ID
            duration_ms = (time.time() - start_time) * 1000
            ACCESS_logger.error(
                "Request failed: %s %s",
                request.method,
                request.url.path,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        # Log request completion (access log channel)
        ACCESS_logger.info(
            "Request completed: %s %s",
            request.method,
            request.url.path,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        # Track slow requests
        if duration_ms > 1000:  # > 1 second
            logger.warning(
                "Slow request detected: %s %s",
                request.method,
                request.url.path,
                extra={
                    "request_id": request_id,
                    "duration_ms": duration_ms,
                    "threshold_ms": 1000,
                },
            )

        return response


# Context variable for request ID (accessible in logs)
_request_id_ctx_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def get_current_request_id() -> str | None:
    """Get the current request ID from context.

    Usage in route handlers:
        request_id = get_current_request_id()
        logger.info("Processing...", extra={"request_id": request_id})

    Returns:
        Request ID string or None if not in request context

    """
    return _request_id_ctx_var.get()


# Custom log filter to inject request ID into all logs
class RequestIDFilter(logging.Filter):
    """Logging filter that adds request_id to all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request_id to log record if available."""
        request_id = _request_id_ctx_var.get()
        if request_id:
            record.request_id = request_id
        return True
