"""Pagination helpers for search APIs (encoding page IDs, iteration)."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def offset_to_page_id(offset: int, has_next: bool) -> str | None:
    """Convert offset to page ID for pagination.

    Args:
        offset: The offset value to encode.
        has_next: Whether there are more pages available.

    Returns:
        str | None: Base64 encoded page ID if has_next is True, None otherwise.

    """
    return base64.b64encode(str(offset).encode()).decode() if has_next else None


def page_id_to_offset(page_id: str | None) -> int:
    """Convert page ID back to offset for pagination.

    Args:
        page_id: Base64 encoded page ID, or None for first page.

    Returns:
        int: The decoded offset value, or 0 if page_id is None, empty, or invalid.

    """
    if not page_id:
        return 0

    try:
        # If it's a numeric string, treat it as direct offset (fallback)
        if page_id.isdigit():
            return int(page_id)

        # Otherwise expect base64
        decoded_bytes = base64.b64decode(page_id, validate=False)
        decoded_str = decoded_bytes.decode()
        if not decoded_str:
            return 0
        return int(decoded_str)
    except Exception:
        # Gracefully handle invalid pagination cursors by resetting to page 0
        return 0


async def iterate(fn: Callable, **kwargs) -> AsyncIterator:
    """Iterate over paged result sets. Assumes that the results sets contain an array of result objects, and a next_page_id."""
    kwargs = {**kwargs, "page_id": None}
    while True:
        result_set = await fn(**kwargs)
        for result in result_set.results:
            yield result
        if result_set.next_page_id is None:
            return
        kwargs["page_id"] = result_set.next_page_id
