"""Request size limiting middleware to prevent DoS attacks.

Limits HTTP request body sizes to prevent resource exhaustion attacks.
This is separate from:
- Token limits (LLM context window)
- Query string limits
- Individual field validation (handled by Pydantic)
"""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.core.logger import app_logger as logger


class RequestSizeLimiter(BaseHTTPMiddleware):
    """Limit HTTP request body size to prevent DoS attacks.

    This middleware enforces a maximum size for request bodies (POST, PUT, PATCH)
    to prevent attackers from sending huge requests that could exhaust server memory.

    Note: This is about HTTP request body size (bytes), NOT:
    - Token limits (LLM context window) - separate concern
    - Query string length - different limit
    - Individual field validation - handled by Pydantic

    Example:
        A POST request with a 50MB JSON body would be blocked if limit is 10MB.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_request_size: int | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize request size limiter.

        Args:
            app: ASGI application (will be set by FastAPI)
            max_request_size: Maximum request body size in bytes.
                             Defaults to 10MB or REQUEST_SIZE_LIMIT_MB env var.
            enabled: Whether to enable request size limiting
        """
        super().__init__(app)
        self.enabled = enabled

        # Get limit from environment or use default
        if max_request_size is None:
            limit_mb = int(os.getenv("REQUEST_SIZE_LIMIT_MB", "10"))
            max_request_size = limit_mb * 1024 * 1024  # Convert MB to bytes

        self.max_request_size = max_request_size

        if self.enabled:
            logger.info(
                "Request size limiting enabled: max %.1fMB",
                self.max_request_size / (1024 * 1024),
            )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check request size before processing.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response or 413 error if request too large

        Raises:
            HTTPException: 413 if request body exceeds limit
        """
        if not self.enabled:
            return await call_next(request)

        # Only check POST, PUT, PATCH (methods that have request bodies)
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        # Check Content-Length header first (fast check)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.max_request_size:
                    logger.warning(
                        "Request rejected: Content-Length %s exceeds limit %s (path: %s)",
                        size,
                        self.max_request_size,
                        request.url.path,
                    )
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request body too large. Maximum size is {self.max_request_size / (1024 * 1024):.1f}MB",
                    )
            except ValueError:
                # Invalid Content-Length header, continue to body check
                pass
        else:
            # No Content-Length header — read and verify actual body size.
            # This covers chunked transfer-encoding and missing headers.
            body = await request.body()
            if len(body) > self.max_request_size:
                logger.warning(
                    "Request rejected: actual body size %s exceeds limit %s (path: %s)",
                    len(body),
                    self.max_request_size,
                    request.url.path,
                )
                raise HTTPException(
                    status_code=413,
                    detail=f"Request body too large. Maximum size is {self.max_request_size / (1024 * 1024):.1f}MB",
                )

        return await call_next(request)
