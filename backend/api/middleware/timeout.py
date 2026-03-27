"""Request timeout middleware to prevent resource exhaustion.

Enforces timeouts on API requests to prevent hanging requests from consuming resources.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.core.logger import forge_logger as logger


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Enforce request timeouts to prevent resource exhaustion.

    This middleware ensures that requests don't hang indefinitely, which could
    lead to resource exhaustion. Different endpoints can have different timeout
    values based on their expected execution time.
    """

    def __init__(
        self,
        app: ASGIApp,
        default_timeout: int | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize request timeout middleware.

        Args:
            app: ASGI application (will be set by FastAPI)
            default_timeout: Default timeout in seconds.
                           Defaults to 30s or REQUEST_TIMEOUT_SEC env var.
            enabled: Whether to enable timeout protection
        """
        super().__init__(app)
        self.enabled = enabled

        # Get timeout from environment or use default
        if default_timeout is None:
            default_timeout = int(os.getenv("REQUEST_TIMEOUT_SEC", "30"))

        self.default_timeout = default_timeout

        # Endpoint-specific timeouts (in seconds)
        # Longer timeouts for operations that legitimately take time
        self.endpoint_timeouts: dict[str, int] = {
            "/api/v1/conversations": 120,  # Conversation creation: MCP init can take 30-60s
            "/api/conversations": 120,  # Legacy path alias
            "/api/v1/llm/chat": 120,  # LLM calls can take 1-2 minutes
            "/api/llm/chat": 120,  # LLM calls can take 1-2 minutes
            "/api/v1/llm/stream": 180,  # Streaming can take even longer
            "/api/llm/stream": 180,  # Streaming can take even longer
            "/api/v1/database-connections/query": 60,  # Database queries
            "/api/database-connections/query": 60,  # Database queries
            "/api/v1/files/upload-files": 60,  # File uploads
            "/api/files/upload-files": 60,  # File uploads
            "/api/v1/memory": 45,  # Memory operations
            "/api/memory": 45,  # Memory operations
        }

        if self.enabled:
            logger.info(
                "Request timeout protection enabled: default %ss, "
                "endpoint-specific timeouts configured for %s endpoints",
                self.default_timeout,
                len(self.endpoint_timeouts),
            )

    def _get_timeout_for_path(self, path: str) -> int:
        """Get timeout for a specific endpoint path.

        Args:
            path: Request path

        Returns:
            Timeout in seconds
        """
        # Check for exact match first
        if path in self.endpoint_timeouts:
            return self.endpoint_timeouts[path]

        # Check for prefix match (e.g., "/api/conversations/123" matches "/api/conversations")
        for endpoint_path, timeout in self.endpoint_timeouts.items():
            if path.startswith(endpoint_path):
                return timeout

        return self.default_timeout

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Enforce timeout on request processing.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response or 504 error if timeout exceeded

        Raises:
            HTTPException: 504 if request exceeds timeout
        """
        if not self.enabled:
            return await call_next(request)

        timeout = self._get_timeout_for_path(request.url.path)

        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except TimeoutError as exc:
            logger.warning(
                "Request timeout: %s %s exceeded %ss timeout",
                request.method,
                request.url.path,
                timeout,
            )
            raise HTTPException(
                status_code=504,
                detail=f"Request timeout. The operation exceeded the {timeout}s time limit. "
                "Please try again or contact support if this persists.",
            ) from exc
