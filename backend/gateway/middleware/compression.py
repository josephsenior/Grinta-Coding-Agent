"""Response compression and caching middleware."""

from __future__ import annotations

import gzip
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.core.constants import (
    CACHE_LONG,
    CACHE_SHORT,
    MIN_COMPRESS_SIZE,
)

if TYPE_CHECKING:
    from fastapi import Request, Response

logger = logging.getLogger(__name__)


class CompressionMiddleware:
    """Middleware to compress responses and add caching headers."""

    # Paths that should have long cache times
    STATIC_PATHS = {
        "/assets/",
        "/fonts/",
        "/images/",
        "/icons/",
        "/favicon.ico",
        "/manifest.json",
    }

    # API paths that can be cached for short periods
    CACHEABLE_API_PATHS = {
        "/api/mcp-marketplace": CACHE_SHORT,
        "/api/memories": CACHE_SHORT,
        "/api/playbooks": CACHE_SHORT,
        # ⚡ PERFORMANCE: Cache high-frequency endpoints
        "/api/monitoring/metrics": 5,  # Monitoring dashboard (5s cache reduces load)
        "/api/monitoring/health": 10,  # Health check (10s cache)
        "/api/settings": 30,  # Settings rarely change (30s cache) ← CRITICAL FIX for concurrent user loading!
        "/api/conversations": 5,  # Conversation list (5s cache)
    }

    def __init__(self, min_compress_size: int = MIN_COMPRESS_SIZE) -> None:
        """Initialize compression middleware.

        Args:
            min_compress_size: Minimum response size to compress (bytes)

        """
        self.min_compress_size = min_compress_size

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Add compression and caching to responses.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Compressed response with cache headers

        """
        response: Response = await call_next(request)

        # Add cache headers
        self._add_cache_headers(request, response)

        # Compress response if applicable
        if self._should_compress(request, response):
            await self._compress_response(response)

        return response

    def _add_cache_headers(self, request: Request, response: Response) -> None:
        """Add appropriate cache headers based on path."""
        path = request.url.path

        if _set_static_cache_headers(path, response, self.STATIC_PATHS):
            return
        if request.method == "GET" and _set_api_cache_headers(path, response, self.CACHEABLE_API_PATHS):
            return

        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    def _should_compress(self, request: Request, response: Response) -> bool:
        """Determine if response should be compressed."""
        if not _client_accepts_gzip(request):
            return False
        if "content-encoding" in response.headers:
            return False
        if not _is_compressible_content_type(response.headers.get("content-type", "")):
            return False
        if _response_too_small(response, self.min_compress_size):
            return False
        return True

    async def _compress_response(self, response: Response) -> None:
        """Compress response body with gzip."""
        try:
            original_body = response.body
            compressed_body = gzip.compress(original_body, compresslevel=6)
            if len(compressed_body) < len(original_body):
                response.body = compressed_body
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Content-Length"] = str(len(compressed_body))
                ratio = (1 - len(compressed_body) / len(original_body)) * 100
                logger.debug(
                    "Compressed response: %sB -> %sB (%.1f%% reduction)",
                    len(original_body),
                    len(compressed_body),
                    ratio,
                )
        except Exception as e:
            logger.warning("Failed to compress response: %s", e)


def _set_static_cache_headers(path: str, response: "Response", static_paths: set) -> bool:
    """Set long cache headers for static paths. Returns True if matched."""
    for static_path in static_paths:
        if path.startswith(static_path) or path.endswith(static_path.replace("/", "")):
            response.headers["Cache-Control"] = f"public, max-age={CACHE_LONG}, immutable"
            response.headers["Vary"] = "Accept-Encoding"
            return True
    return False


def _set_api_cache_headers(path: str, response: "Response", cacheable_paths: dict) -> bool:
    """Set cache headers for cacheable API paths. Returns True if matched."""
    for api_path, cache_time in cacheable_paths.items():
        if path.startswith(api_path):
            response.headers["Cache-Control"] = f"public, max-age={cache_time}, must-revalidate"
            response.headers["Vary"] = "Accept-Encoding"
            if hasattr(response, "body"):
                import hashlib
                etag = hashlib.sha256(response.body).hexdigest()[:16]
                response.headers["ETag"] = f'"{etag}"'
            return True
    return False


def _client_accepts_gzip(request: "Request") -> bool:
    """True if client Accept-Encoding includes gzip."""
    return "gzip" in request.headers.get("accept-encoding", "").lower()


def _is_compressible_content_type(content_type: str) -> bool:
    """True if content type is compressible (text-based)."""
    compressible = ("application/json", "text/", "application/javascript", "application/xml")
    return any(ct in content_type for ct in compressible)


def _response_too_small(response: "Response", min_size: int) -> bool:
    """True if response body is smaller than min_size."""
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) < min_size:
                return True
        except (ValueError, OverflowError):
            # Invalid Content-Length header, skip size check
            pass
    if not hasattr(response, "body") or not response.body:
        return True
    return len(response.body) < min_size


class ResponseSizeOptimizer:
    """Middleware to optimize response payload sizes."""

    # Fields to exclude from responses to reduce size
    EXCLUDE_FIELDS = {
        "created_at",  # Often not needed in list views
        "updated_at",  # Often not needed in list views
        "__v",  # MongoDB version field
    }

    @staticmethod
    def optimize_list_response(
        items: list[dict], exclude_fields: set[str] | None = None
    ) -> list[dict]:
        """Optimize list responses by removing unnecessary fields.

        Args:
            items: List of items to optimize
            exclude_fields: Additional fields to exclude

        Returns:
            Optimized list of items

        """
        if exclude_fields:
            all_exclude = ResponseSizeOptimizer.EXCLUDE_FIELDS | exclude_fields
        else:
            all_exclude = ResponseSizeOptimizer.EXCLUDE_FIELDS

        return [
            {k: v for k, v in item.items() if k not in all_exclude} for item in items
        ]

    @staticmethod
    def paginate_response(
        items: list,
        page: int = 1,
        page_size: int = 50,
        max_page_size: int = 100,
    ) -> dict:
        """Paginate responses to reduce payload sizes.

        Args:
            items: Full list of items
            page: Page number (1-indexed)
            page_size: Items per page
            max_page_size: Maximum allowed page size

        Returns:
            Paginated response with metadata

        """
        # Clamp page_size to max
        page_size = min(page_size, max_page_size)

        # Calculate pagination
        total = len(items)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size

        return {
            "items": items[start:end],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        }
