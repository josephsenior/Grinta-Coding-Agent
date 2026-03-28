"""Request ID middleware for tracking requests across the system.

Adds a unique request ID to each request for tracing and debugging.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID to all requests."""

    async def dispatch(self, request: Request, call_next):
        """Process request and add request ID."""
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Add to request state
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


def get_request_id(request: Request) -> str:
    """Get request ID from request state.

    Args:
        request: FastAPI request

    Returns:
        Request ID string
    """
    try:
        return getattr(request.state, "request_id", "unknown")
    except AttributeError:
        return "unknown"
