"""Token-based authentication middleware."""

import logging
import os
import secrets

from fastapi import Request, status
from fastapi.security.utils import get_authorization_scheme_param
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def get_session_api_key() -> str:
    """Get the session API key from server configuration."""
    from backend.server.shared import server_config

    return server_config.session_api_key


class SimpleTokenAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce session-based authentication."""

    async def dispatch(self, request: Request, call_next):
        # Allow OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow health checks and static resources without auth
        # NOTE: /mcp/ is intentionally public — runtime connects via server-to-server
        # MCP protocol which has its own auth layer (api_key in MCP config).
        # NOTE: /api/monitoring/ is NOT public — requires auth to prevent info leaks.
        public_paths = [
            "/api/auth/",
            "/docs",
            "/openapi.json",
            "/favicon.ico",
            "/alive",
            "/api/health/live",
            "/api/health/ready",
            "/api/v1/conversations/test",
            "/assets/",
            "/locales/",
            "/mcp/",
            "/static/",
        ]
        if any(request.url.path.startswith(path) for path in public_paths):
            return await call_next(request)

        # Bypass auth in local runtime mode
        expected_key = get_session_api_key()
        if (
            os.environ.get("FORGE_RUNTIME") == "local"
            or os.environ.get("SESSION_API_KEY") == ""
            or not expected_key
        ):
            return await call_next(request)

        # Check for X-Session-API-Key header (Preferred)
        header_key = request.headers.get("X-Session-API-Key")

        # Check for token in Authorization Header (Bearer)
        authorization = request.headers.get("Authorization")
        scheme, bearer_token = get_authorization_scheme_param(authorization)

        # Verify Key
        is_valid = False
        if (
            header_key
            and secrets.compare_digest(header_key, expected_key)
            or scheme.lower() == "bearer"
            and bearer_token
            and secrets.compare_digest(bearer_token, expected_key)
        ):
            is_valid = True

        if not is_valid:
            logger.warning("Unauthorized access attempt to %s", request.url.path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing X-Session-API-Key"},
            )

        return await call_next(request)
