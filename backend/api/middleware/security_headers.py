"""Security headers middleware for forge."""

import os
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse


class SecurityHeadersMiddleware:
    """Middleware to add security headers to all responses."""

    def __init__(self, enabled: bool = True, csp_profile: str = "permissive") -> None:
        """Initialize security headers middleware.

        Args:
            enabled: Whether to add security headers
            csp_profile: CSP profile to apply ("permissive" | "strict")

        """
        self.enabled = enabled
        self.csp_profile = (csp_profile or "permissive").lower()

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response with security headers

        """
        response = await call_next(request)

        if not self.enabled:
            return response

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Enable XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Force HTTPS in production
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Content Security Policy
        # Two profiles: permissive (dev-friendly) and strict (production)
        if self.csp_profile == "strict":
            csp_directives = [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self'",
                "img-src 'self' data: https:",
                "font-src 'self'",
                "connect-src 'self'",
                "frame-src 'none'",
                "worker-src 'self'",
                "object-src 'none'",
                "base-uri 'self'",
                "form-action 'self'",
                "frame-ancestors 'none'",
                "upgrade-insecure-requests",
            ]
        else:
            csp_directives = [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # Required for Monaco, Mermaid
                "style-src 'self' 'unsafe-inline'",  # Required for Tailwind, inline styles
                "img-src 'self' data: https:",  # Allow images from data URLs and HTTPS
                "font-src 'self' data:",
                "connect-src 'self' ws: wss: https:",  # Allow WebSocket and API connections
                "frame-src 'self'",  # Allow iframes from same origin (served apps)
                "worker-src 'self' blob:",  # Allow web workers
                "object-src 'none'",  # Disallow plugins
                "base-uri 'self'",  # Restrict base tag
                "form-action 'self'",  # Restrict form submissions
                "frame-ancestors 'none'",  # Prevent embedding
                "upgrade-insecure-requests",  # Upgrade HTTP to HTTPS
            ]

        # Optional reporting endpoint
        report_uri = os.getenv("CSP_REPORT_URI")
        if report_uri:
            csp_directives.append(f"report-uri {report_uri}")

        # Support report-only mode for staging
        if os.getenv("CSP_REPORT_ONLY", "0").lower() in {"1", "true", "yes"}:
            response.headers["Content-Security-Policy-Report-Only"] = "; ".join(
                csp_directives
            )
        else:
            response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # Permissions Policy (formerly Feature-Policy)
        permissions_directives = [
            "camera=()",  # Disable camera
            "microphone=()",  # Disable microphone
            "geolocation=()",  # Disable geolocation
            "payment=()",  # Disable payment API
            "usb=()",  # Disable USB access
            "magnetometer=()",  # Disable magnetometer
            "gyroscope=()",  # Disable gyroscope
            "accelerometer=()",  # Disable accelerometer
        ]
        response.headers["Permissions-Policy"] = ", ".join(permissions_directives)

        # Cross-Origin Policies (modern security)
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # X-Permitted-Cross-Domain-Policies (Adobe products)
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        return response


class CSRFProtection:
    """CSRF protection middleware."""

    # Methods that require CSRF protection
    PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    # Paths to skip CSRF check (e.g., webhooks with signature verification)
    SKIP_PATHS: set[str] = set()

    def __init__(self, enabled: bool = True) -> None:
        """Initialize CSRF protection.

        Args:
            enabled: Whether CSRF protection is enabled

        """
        self.enabled = enabled

    def _should_skip_csrf_check(self, request: Request) -> bool:
        """Check if CSRF check should be skipped.

        Args:
            request: FastAPI request

        Returns:
            True if check should be skipped

        """
        if not self.enabled:
            return True
        if request.method not in self.PROTECTED_METHODS:
            return True
        if request.url.path in self.SKIP_PATHS:
            return True
        return False

    def _validate_origin_header(
        self, origin: str, request_host: str
    ) -> tuple[bool, str]:
        """Validate Origin header matches request host.

        Args:
            origin: Origin header value
            request_host: Request host URL

        Returns:
            Tuple of (is_valid, error_message)

        """
        if not origin.startswith(request_host) and not self._is_localhost_development(
            origin, request_host
        ):
            return False, "CSRF validation failed: Origin mismatch"
        return True, ""

    def _validate_referer_header(
        self, referer: str, request_host: str
    ) -> tuple[bool, str]:
        """Validate Referer header matches request host.

        Args:
            referer: Referer header value
            request_host: Request host URL

        Returns:
            Tuple of (is_valid, error_message)

        """
        if not referer.startswith(request_host) and not self._is_localhost_development(
            referer, request_host
        ):
            return False, "CSRF validation failed: Referer mismatch"
        return True, ""

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Validate CSRF for state-changing requests.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response or CSRF error

        """
        if self._should_skip_csrf_check(request):
            return await call_next(request)

        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")

        if not origin and not referer:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF validation failed: Missing Origin/Referer header"
                },
            )

        request_host = f"{request.url.scheme}://{request.url.netloc}"

        if origin:
            is_valid, error_msg = self._validate_origin_header(origin, request_host)
            if not is_valid:
                return JSONResponse(status_code=403, content={"detail": error_msg})

        if referer:
            is_valid, error_msg = self._validate_referer_header(referer, request_host)
            if not is_valid:
                return JSONResponse(status_code=403, content={"detail": error_msg})

        return await call_next(request)

    def _is_localhost_development(self, origin: str, request_host: str) -> bool:
        """Check if this is a localhost development scenario (different ports)."""
        try:
            from urllib.parse import urlparse

            origin_parsed = urlparse(origin)
            request_parsed = urlparse(request_host)

            # Both must be localhost/127.0.0.1
            origin_host = origin_parsed.hostname
            request_hostname = request_parsed.hostname

            is_localhost = origin_host in (
                "localhost",
                "127.0.0.1",
            ) and request_hostname in ("localhost", "127.0.0.1")
            same_scheme = origin_parsed.scheme == request_parsed.scheme

            return is_localhost and same_scheme
        except Exception:
            return False
