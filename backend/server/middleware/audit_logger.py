"""Audit logging middleware for sensitive operations."""

from __future__ import annotations

import json
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.core.logger import FORGE_logger as logger


# Sensitive operations that require audit logging
AUDIT_OPERATIONS = {
    "POST /api/v1/settings": "settings_update",
    "PATCH /api/v1/settings": "settings_update",
    "POST /api/v1/secrets": "secrets_create",
    "PUT /api/v1/secrets": "secrets_update",
    "PATCH /api/v1/secrets": "secrets_update",
    "DELETE /api/v1/secrets": "secrets_delete",
    "DELETE /api/v1/conversations": "conversation_delete",
    "POST /api/v1/conversations": "conversation_create",
}


class AuditLoggerMiddleware(BaseHTTPMiddleware):
    """Middleware that logs sensitive operations for audit trail."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process request and log sensitive operations."""
        # Determine if this is a sensitive operation
        operation_key = f"{request.method} {request.url.path}"
        audit_action = None

        # Match exact paths first, then pattern match for routes with parameters
        for pattern, action in AUDIT_OPERATIONS.items():
            if self._matches_pattern(operation_key, pattern):
                audit_action = action
                break

        start_time = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000

        # Only log if this was a sensitive operation and successful (2xx status)
        if audit_action and 200 <= response.status_code < 300:
            await self._log_audit_event(
                request=request,
                response=response,
                action=audit_action,
                duration_ms=duration_ms,
            )

        return response

    def _matches_pattern(self, operation: str, pattern: str) -> bool:
        """Match operation against pattern, handling path parameters."""
        # Exact match
        if operation == pattern:
            return True

        # Pattern match for paths with parameters
        op_parts = operation.split(maxsplit=1)
        pattern_parts = pattern.split(maxsplit=1)

        if len(op_parts) != 2 or len(pattern_parts) != 2:
            return False

        op_method, op_path = op_parts
        pat_method, pat_path = pattern_parts

        # Method must match exactly
        if op_method != pat_method:
            return False

        # Path matching with parameter support
        return self._path_matches(op_path, pat_path)

    def _path_matches(self, path: str, pattern: str) -> bool:
        """Match path against pattern supporting {param} placeholders."""
        path_segments = path.split("/")
        pattern_segments = pattern.split("/")

        if len(path_segments) != len(pattern_segments):
            return False

        for path_seg, pattern_seg in zip(path_segments, pattern_segments, strict=True):
            # Pattern segment is a parameter placeholder
            if pattern_seg.startswith("{") and pattern_seg.endswith("}"):
                continue
            # Literal match required
            if path_seg != pattern_seg:
                return False

        return True

    async def _log_audit_event(
        self,
        request: Request,
        response: Response,
        action: str,
        duration_ms: float,
    ) -> None:
        """Log audit event in structured format."""
        # Extract user info from headers or request state
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # Try to get from headers (JWT, session, etc.)
            user_id = request.headers.get("X-User-ID", "unknown")

        # Build audit log entry
        audit_entry: dict[str, Any] = {
            "timestamp": time.time(),
            "action": action,
            "user_id": user_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "ip_address": self._get_client_ip(request),
            "user_agent": request.headers.get("user-agent", "unknown"),
        }

        # Add resource identifier for specific actions
        if "conversation" in action:
            conversation_id = self._extract_conversation_id(request.url.path)
            if conversation_id:
                audit_entry["resource_id"] = conversation_id
                audit_entry["resource_type"] = "conversation"

        # Log as structured JSON for easy parsing and filtering
        logger.info(
            "🔒 AUDIT: %s",
            json.dumps(audit_entry, indent=None, separators=(",", ":")),
            extra={"audit": True, **audit_entry},
        )

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        # Check common proxy headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can be a comma-separated list
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client
        if request.client:
            return request.client.host

        return "unknown"

    def _extract_conversation_id(self, path: str) -> str | None:
        """Extract conversation ID from path like /api/v1/conversations/{id}."""
        parts = path.split("/")
        try:
            # Pattern: /api/v1/conversations/{conversation_id}
            if "conversations" in parts:
                idx = parts.index("conversations")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        except (ValueError, IndexError):
            pass
        return None
