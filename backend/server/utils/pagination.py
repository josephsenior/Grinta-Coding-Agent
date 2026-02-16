"""Pagination utilities for API endpoints.

Provides standardized pagination using cursor-based and offset-based approaches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


@dataclass
class PaginationParams:
    """Pagination parameters for requests."""

    page: int = 1
    limit: int = 20
    cursor: str | None = None
    max_limit: int = 100

    def __post_init__(self):
        """Validate and normalize pagination parameters."""
        if self.page < 1:
            self.page = 1
        if self.limit < 1:
            self.limit = 20
        if self.limit > self.max_limit:
            self.limit = self.max_limit

    @property
    def offset(self) -> int:
        """Calculate offset from page and limit."""
        return (self.page - 1) * self.limit


class PaginatedResponse[T](BaseModel):
    """Standardized paginated response model."""

    data: list[T] = Field(..., description="List of items")
    pagination: dict[str, Any] = Field(..., description="Pagination metadata")

    @classmethod
    def create(
        cls,
        items: list[T],
        page: int,
        limit: int,
        total: int | None = None,
        next_cursor: str | None = None,
        has_more: bool | None = None,
    ) -> PaginatedResponse[T]:
        """Create a paginated response.

        Args:
            items: List of items for current page
            page: Current page number
            limit: Items per page
            total: Total number of items (optional)
            next_cursor: Cursor for next page (optional, for cursor-based pagination)
            has_more: Whether there are more items (optional)

        Returns:
            PaginatedResponse instance
        """
        # Calculate has_more if not provided
        if has_more is None:
            if total is not None:
                has_more = (page * limit) < total
            else:
                has_more = len(items) == limit

        pagination_meta: dict[str, Any] = {
            "page": page,
            "limit": limit,
            "has_more": has_more,
        }

        if total is not None:
            pagination_meta["total"] = total
            pagination_meta["total_pages"] = (total + limit - 1) // limit

        if next_cursor:
            pagination_meta["next_cursor"] = next_cursor

        return cls(data=items, pagination=pagination_meta)


class CursorPaginationParams(BaseModel):
    """Cursor-based pagination parameters."""

    cursor: str | None = Field(None, description="Cursor for pagination")
    limit: int = Field(20, ge=1, le=100, description="Number of items per page")

    def __post_init__(self):
        """Validate limit."""
        if self.limit > 100:
            self.limit = 100
        if self.limit < 1:
            self.limit = 20


class OffsetPaginationParams(BaseModel):
    """Offset-based pagination parameters."""

    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(20, ge=1, le=100, description="Number of items per page")

    @property
    def offset(self) -> int:
        """Calculate offset from page and limit."""
        return (self.page - 1) * self.limit


def parse_pagination_params(
    page: int | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> PaginationParams:
    """Parse pagination parameters from query string.

    Args:
        page: Page number (for offset-based pagination)
        limit: Items per page
        cursor: Cursor token (for cursor-based pagination)

    Returns:
        PaginationParams instance
    """
    return PaginationParams(
        page=page or 1,
        limit=limit or 20,
        cursor=cursor,
    )
