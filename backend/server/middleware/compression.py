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
        """Add appropriate cache headers based on path.

        Args:
            request: FastAPI request
            response: Response to add headers to

        """
        path = request.url.path

        # Check if it's a static asset
        for static_path in self.STATIC_PATHS:
            if path.startswith(static_path) or path.endswith(
                static_path.replace("/", "")
            ):
                response.headers["Cache-Control"] = (
                    f"public, max-age={CACHE_LONG}, immutable"
                )
                response.headers["Vary"] = "Accept-Encoding"
                return

        # Check if it's a cacheable API endpoint (GET requests only)
        if request.method == "GET":
            for api_path, cache_time in self.CACHEABLE_API_PATHS.items():
                if path.startswith(api_path):
                    response.headers["Cache-Control"] = (
                        f"public, max-age={cache_time}, must-revalidate"
                    )
                    response.headers["Vary"] = "Accept-Encoding"
                    # Add ETag for validation
                    if hasattr(response, "body"):
                        etag = str(hash(response.body))
                        response.headers["ETag"] = f'"{etag}"'
                    return

        # Default: No cache for dynamic content
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    def _should_compress(self, request: Request, response: Response) -> bool:
        """Determine if response should be compressed.

        Args:
            request: FastAPI request
            response: Response to potentially compress

        Returns:
            True if compression should be applied

        """
        # Check if client accepts gzip
        accept_encoding = request.headers.get("accept-encoding", "")
        if "gzip" not in accept_encoding.lower():
            return False

        # Check if response is already compressed
        if "content-encoding" in response.headers:
            return False

        # Check content type (only compress text-based responses)
        content_type = response.headers.get("content-type", "")
        compressible_types = [
            "application/json",
            "text/",
            "application/javascript",
            "application/xml",
        ]
        if not any(ct in content_type for ct in compressible_types):
            return False

        # Check response size
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) < self.min_compress_size:
            return False

        # Check if body exists
        if not hasattr(response, "body") or not response.body:
            return False

        # Check body size
        return not len(response.body) < self.min_compress_size

    async def _compress_response(self, response: Response) -> None:
        """Compress response body with gzip.

        Args:
            response: Response to compress

        """
        try:
            # Get original body
            original_body = response.body

            # Compress
            compressed_body = gzip.compress(original_body, compresslevel=6)

            # Only use compression if it actually reduces size
            if len(compressed_body) < len(original_body):
                response.body = compressed_body
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Content-Length"] = str(len(compressed_body))

                original_size = len(original_body)
                compressed_size = len(compressed_body)
                ratio = (1 - compressed_size / original_size) * 100

                logger.debug(
                    "Compressed response: %sB -> %sB (%.1f%% reduction)",
                    original_size,
                    compressed_size,
                    ratio,
                )
        except Exception as e:
            logger.warning("Failed to compress response: %s", e)


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
