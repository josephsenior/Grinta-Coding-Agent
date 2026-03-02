"""Tests for backend.api.utils.pagination — Pagination utilities."""

from __future__ import annotations

from typing import Any

from backend.api.utils.pagination import (
    OffsetPaginationParams,
    PaginatedResponse,
    PaginationParams,
    parse_pagination_params,
)


# ---------------------------------------------------------------------------
# PaginationParams
# ---------------------------------------------------------------------------


class TestPaginationParams:
    """Tests for the PaginationParams dataclass."""

    def test_defaults(self):
        p = PaginationParams()
        assert p.page == 1
        assert p.limit == 20
        assert p.cursor is None
        assert p.max_limit == 100

    def test_custom_values(self):
        p = PaginationParams(page=3, limit=50)
        assert p.page == 3
        assert p.limit == 50

    def test_page_clamped_to_1(self):
        p = PaginationParams(page=0)
        assert p.page == 1
        p2 = PaginationParams(page=-5)
        assert p2.page == 1

    def test_limit_below_1_reset_to_20(self):
        p = PaginationParams(limit=0)
        assert p.limit == 20
        p2 = PaginationParams(limit=-3)
        assert p2.limit == 20

    def test_limit_above_max_clamped(self):
        p = PaginationParams(limit=200, max_limit=100)
        assert p.limit == 100

    def test_custom_max_limit(self):
        p = PaginationParams(limit=60, max_limit=50)
        assert p.limit == 50

    def test_offset_property(self):
        p = PaginationParams(page=1, limit=20)
        assert p.offset == 0
        p2 = PaginationParams(page=3, limit=10)
        assert p2.offset == 20

    def test_offset_page_1(self):
        p = PaginationParams(page=1, limit=50)
        assert p.offset == 0


# ---------------------------------------------------------------------------
# PaginatedResponse
# ---------------------------------------------------------------------------


class TestPaginatedResponse:
    """Tests for the PaginatedResponse model."""

    def test_create_basic(self):
        resp = PaginatedResponse.create(
            items=["a", "b", "c"],
            page=1,
            limit=10,
            total=3,
        )
        assert resp.data == ["a", "b", "c"]
        assert resp.pagination["page"] == 1
        assert resp.pagination["limit"] == 10
        assert resp.pagination["total"] == 3
        assert resp.pagination["has_more"] is False

    def test_create_has_more_from_total(self):
        resp = PaginatedResponse.create(
            items=list(range(10)),
            page=1,
            limit=10,
            total=25,
        )
        assert resp.pagination["has_more"] is True
        assert resp.pagination["total_pages"] == 3

    def test_create_has_more_false_last_page(self):
        resp = PaginatedResponse.create(
            items=list(range(5)),
            page=3,
            limit=10,
            total=25,
        )
        assert resp.pagination["has_more"] is False

    def test_create_has_more_inferred_from_items(self):
        """When total is None, has_more = len(items) == limit."""
        resp = PaginatedResponse.create(
            items=list(range(10)),
            page=1,
            limit=10,
        )
        assert resp.pagination["has_more"] is True

    def test_create_has_more_inferred_false(self):
        resp = PaginatedResponse.create(
            items=list(range(5)),
            page=1,
            limit=10,
        )
        assert resp.pagination["has_more"] is False

    def test_create_explicit_has_more(self):
        resp = PaginatedResponse.create(
            items=["x"],
            page=1,
            limit=10,
            has_more=True,
        )
        assert resp.pagination["has_more"] is True

    def test_total_pages_calculation(self):
        resp: Any = PaginatedResponse.create(items=[], page=1, limit=10, total=0)
        assert resp.pagination["total_pages"] == 0

        resp2: Any = PaginatedResponse.create(items=[], page=1, limit=10, total=1)
        assert resp2.pagination["total_pages"] == 1

        resp3: Any = PaginatedResponse.create(items=[], page=1, limit=10, total=10)
        assert resp3.pagination["total_pages"] == 1

        resp4: Any = PaginatedResponse.create(items=[], page=1, limit=10, total=11)
        assert resp4.pagination["total_pages"] == 2

    def test_next_cursor_included(self):
        resp: Any = PaginatedResponse.create(
            items=["a"],
            page=1,
            limit=10,
            next_cursor="abc123",
        )
        assert resp.pagination["next_cursor"] == "abc123"

    def test_no_total_no_total_pages(self):
        resp: Any = PaginatedResponse.create(items=[], page=1, limit=10)
        assert "total" not in resp.pagination
        assert "total_pages" not in resp.pagination


# ---------------------------------------------------------------------------
# OffsetPaginationParams
# ---------------------------------------------------------------------------


class TestOffsetPaginationParams:
    """Tests for the OffsetPaginationParams model."""

    def test_defaults(self):
        p = OffsetPaginationParams()
        assert p.page == 1
        assert p.limit == 20
        assert p.offset == 0

    def test_offset(self):
        p = OffsetPaginationParams(page=5, limit=10)
        assert p.offset == 40


# ---------------------------------------------------------------------------
# parse_pagination_params
# ---------------------------------------------------------------------------


class TestParsePaginationParams:
    """Tests for the parse_pagination_params function."""

    def test_defaults(self):
        p = parse_pagination_params()
        assert p.page == 1
        assert p.limit == 20
        assert p.cursor is None

    def test_with_values(self):
        p = parse_pagination_params(page=3, limit=50, cursor="xyz")
        assert p.page == 3
        assert p.limit == 50
        assert p.cursor == "xyz"

    def test_none_falls_back(self):
        p = parse_pagination_params(page=None, limit=None)
        assert p.page == 1
        assert p.limit == 20
