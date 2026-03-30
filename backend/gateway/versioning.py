"""API Versioning Infrastructure for App.

Policy (as of aggressive cleanup milestone):
- All routes live under ``/api/…`` **without** a version segment.
- The ``API-Version`` response header always reflects ``CURRENT_VERSION``.
- When a v2 is introduced, routes will be registered via
  ``create_versioned_router`` and the middleware will enforce version paths.
- ``ENFORCE_API_VERSIONING`` is **off** until v2 ships.

Removed dead code: ``create_versioned_router``, ``supports_version``,
``api_route`` decorator — they were defined but never called.
"""

from collections.abc import Callable
from enum import Enum

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from backend.gateway.constants import ENFORCE_API_VERSIONING


class APIVersion(str, Enum):
    """Supported API versions."""

    V1 = "v1"


CURRENT_VERSION = APIVersion.V1
MINIMUM_SUPPORTED_VERSION = APIVersion.V1

# Version sunset dates (format: YYYY-MM-DD) — empty until v2
SUNSET_DATES: dict[APIVersion, str] = {}


def get_api_version_from_path(path: str) -> str | None:
    """Extract API version from request path (e.g. ``/api/v1/…``)."""
    parts = path.split("/")
    if len(parts) >= 3 and parts[1] == "api" and parts[2].startswith("v"):
        return parts[2]
    return None


def add_version_headers(response: Response, version: str) -> None:
    """Add ``API-Version`` response header."""
    response.headers["API-Version"] = version


# Paths that skip versioning entirely
_EXCLUDED_PATHS = (
    "/api/health/live",
    "/api/health/ready",
    "/api/monitoring/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/mcp",
    "/assets",
    "/static",
    "/favicon.ico",
    "/ws",
    "/api/ws",
    "/api/monitoring/ws",
)


def _is_version_excluded_path(path: str) -> bool:
    """True if path skips versioning (health, docs, ws, etc)."""
    return any(path.startswith(p) for p in _EXCLUDED_PATHS)


def _reject_missing_version(path: str) -> JSONResponse:
    """Return 400 when versioned path is required but missing."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "missing_api_version",
            "message": f"Use /api/{CURRENT_VERSION.value}/… format.",
            "current_version": CURRENT_VERSION.value,
            "suggested_path": path.replace("/api/", f"/api/{CURRENT_VERSION.value}/", 1),
        },
    )


def _requires_version_rejection(path: str, version: str | None) -> bool:
    """True if request should be rejected for missing API version."""
    return (
        not version
        and path.startswith("/api/")
        and ENFORCE_API_VERSIONING
    )


async def version_middleware(request: Request, call_next: Callable) -> Response:
    """Lightweight middleware: attach ``API-Version`` header to every /api/ response."""
    path = request.url.path

    if _is_version_excluded_path(path):
        return await call_next(request)

    version = get_api_version_from_path(path)
    if _requires_version_rejection(path, version):
        return _reject_missing_version(path)

    response = await call_next(request)
    if path.startswith("/api/"):
        response.headers["API-Version"] = version or CURRENT_VERSION.value
    return response
