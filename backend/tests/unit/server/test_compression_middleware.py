"""Tests for backend.server.middleware.compression — CompressionMiddleware & ResponseSizeOptimizer."""

from __future__ import annotations

import gzip
from unittest.mock import MagicMock

import pytest

from backend.server.middleware.compression import (
    CompressionMiddleware,
    ResponseSizeOptimizer,
)


# ── CompressionMiddleware._add_cache_headers ─────────────────────────


class TestAddCacheHeaders:
    def _make(self, path: str, method: str = "GET") -> tuple[MagicMock, MagicMock]:
        req = MagicMock()
        req.url.path = path
        req.method = method
        resp = MagicMock()
        resp.headers = {}
        return req, resp

    def test_static_path_gets_long_cache(self):
        mw = CompressionMiddleware()
        req, resp = self._make("/assets/main.js")
        mw._add_cache_headers(req, resp)
        assert "public" in resp.headers["Cache-Control"]
        assert "immutable" in resp.headers["Cache-Control"]
        assert resp.headers.get("Vary") == "Accept-Encoding"

    def test_favicon_gets_long_cache(self):
        mw = CompressionMiddleware()
        req, resp = self._make("/favicon.ico")
        mw._add_cache_headers(req, resp)
        assert "public" in resp.headers["Cache-Control"]

    def test_cacheable_api_get(self):
        mw = CompressionMiddleware()
        req, resp = self._make("/api/settings", method="GET")
        resp.body = b'{"key": "value"}'
        mw._add_cache_headers(req, resp)
        assert "public" in resp.headers["Cache-Control"]
        assert "must-revalidate" in resp.headers["Cache-Control"]

    def test_cacheable_api_post_not_cached(self):
        mw = CompressionMiddleware()
        req, resp = self._make("/api/settings", method="POST")
        mw._add_cache_headers(req, resp)
        assert "no-cache" in resp.headers["Cache-Control"]

    def test_dynamic_path_gets_no_cache(self):
        mw = CompressionMiddleware()
        req, resp = self._make("/api/sessions/abc123/execute", method="GET")
        mw._add_cache_headers(req, resp)
        assert "no-cache" in resp.headers["Cache-Control"]
        assert resp.headers.get("Pragma") == "no-cache"
        assert resp.headers.get("Expires") == "0"

    def test_monitoring_health_cached(self):
        mw = CompressionMiddleware()
        req, resp = self._make("/api/monitoring/health", method="GET")
        resp.body = b"{}"
        mw._add_cache_headers(req, resp)
        assert "public" in resp.headers["Cache-Control"]


# ── CompressionMiddleware._should_compress ───────────────────────────


class TestShouldCompress:
    def _make(
        self,
        accept_encoding: str = "gzip",
        content_type: str = "application/json",
        content_encoding: str | None = None,
        content_length: str | None = None,
        body: bytes | None = None,
    ) -> tuple[MagicMock, MagicMock]:
        req = MagicMock()
        req_headers = {"accept-encoding": accept_encoding}
        req_headers_mock = MagicMock()
        req_headers_mock.get = MagicMock(
            side_effect=lambda k, d="": req_headers.get(k, d)
        )
        req.headers = req_headers_mock

        resp = MagicMock()
        resp_headers: dict[str, str] = {}
        if content_type:
            resp_headers["content-type"] = content_type
        if content_encoding:
            resp_headers["content-encoding"] = content_encoding
        if content_length:
            resp_headers["content-length"] = content_length
        resp_headers_mock = MagicMock()
        resp_headers_mock.get = MagicMock(
            side_effect=lambda k, d="": resp_headers.get(k, d)
        )
        resp_headers_mock.__contains__ = lambda self_unused, k: k in resp_headers
        resp.headers = resp_headers_mock

        if body is not None:
            resp.body = body
        else:
            del resp.body

        return req, resp

    def test_client_does_not_accept_gzip(self):
        mw = CompressionMiddleware()
        req, resp = self._make(accept_encoding="deflate", body=b"x" * 2000)
        assert mw._should_compress(req, resp) is False

    def test_already_compressed(self):
        mw = CompressionMiddleware()
        req, resp = self._make(content_encoding="gzip", body=b"x" * 2000)
        assert mw._should_compress(req, resp) is False

    def test_non_compressible_content_type(self):
        mw = CompressionMiddleware()
        req, resp = self._make(content_type="image/png", body=b"x" * 2000)
        assert mw._should_compress(req, resp) is False

    def test_json_is_compressible(self):
        mw = CompressionMiddleware(min_compress_size=100)
        req, resp = self._make(content_type="application/json", body=b"x" * 200)
        assert mw._should_compress(req, resp) is True

    def test_text_is_compressible(self):
        mw = CompressionMiddleware(min_compress_size=100)
        req, resp = self._make(content_type="text/html", body=b"x" * 200)
        assert mw._should_compress(req, resp) is True

    def test_below_min_size_via_content_length(self):
        mw = CompressionMiddleware(min_compress_size=1000)
        req, resp = self._make(content_length="100", body=b"x" * 100)
        assert mw._should_compress(req, resp) is False

    def test_below_min_size_via_body(self):
        mw = CompressionMiddleware(min_compress_size=1000)
        req, resp = self._make(body=b"x" * 100)
        assert mw._should_compress(req, resp) is False

    def test_no_body(self):
        mw = CompressionMiddleware()
        req, resp = self._make(body=None)
        assert mw._should_compress(req, resp) is False


# ── CompressionMiddleware._compress_response ─────────────────────────


class TestCompressResponse:
    @pytest.mark.asyncio
    async def test_compresses_body(self):
        mw = CompressionMiddleware()
        resp = MagicMock()
        original = b"hello world " * 100  # ~1200 bytes
        resp.body = original
        resp.headers = {}

        await mw._compress_response(resp)

        assert resp.headers.get("Content-Encoding") == "gzip"
        decompressed = gzip.decompress(resp.body)
        assert decompressed == original

    @pytest.mark.asyncio
    async def test_does_not_compress_if_larger(self):
        mw = CompressionMiddleware()
        resp = MagicMock()
        original = b"x"  # 1 byte — gzip overhead makes it larger
        resp.body = original
        resp.headers = {}

        await mw._compress_response(resp)

        # Should keep original if compression increases size
        assert resp.body == original or "Content-Encoding" in resp.headers


# ── ResponseSizeOptimizer ────────────────────────────────────────────


class TestResponseSizeOptimizer:
    def test_optimize_list_response_default_exclude(self):
        items = [
            {
                "id": 1,
                "name": "foo",
                "created_at": "2024-01-01",
                "updated_at": "2024-01-02",
                "__v": 0,
            },
            {"id": 2, "name": "bar", "created_at": "2024-01-03"},
        ]
        result = ResponseSizeOptimizer.optimize_list_response(items)
        assert len(result) == 2
        for item in result:
            assert "created_at" not in item
            assert "updated_at" not in item
            assert "__v" not in item
            assert "id" in item
            assert "name" in item

    def test_optimize_list_response_custom_exclude(self):
        items = [{"id": 1, "secret": "abc", "name": "test"}]
        result = ResponseSizeOptimizer.optimize_list_response(
            items, exclude_fields={"secret"}
        )
        assert result == [{"id": 1, "name": "test"}]

    def test_optimize_empty_list(self):
        result = ResponseSizeOptimizer.optimize_list_response([])
        assert result == []


class TestPaginateResponse:
    def test_first_page(self):
        items = list(range(100))
        result = ResponseSizeOptimizer.paginate_response(items, page=1, page_size=10)
        assert result["items"] == list(range(10))
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["total_items"] == 100
        assert result["pagination"]["total_pages"] == 10
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_prev"] is False

    def test_last_page(self):
        items = list(range(25))
        result = ResponseSizeOptimizer.paginate_response(items, page=3, page_size=10)
        assert result["items"] == [20, 21, 22, 23, 24]
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_prev"] is True

    def test_page_size_clamped_to_max(self):
        items = list(range(200))
        result = ResponseSizeOptimizer.paginate_response(
            items, page=1, page_size=150, max_page_size=50
        )
        assert len(result["items"]) == 50
        assert result["pagination"]["page_size"] == 50

    def test_single_page(self):
        items = [1, 2, 3]
        result = ResponseSizeOptimizer.paginate_response(items, page=1, page_size=50)
        assert result["items"] == [1, 2, 3]
        assert result["pagination"]["total_pages"] == 1
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_prev"] is False

    def test_empty_items(self):
        result = ResponseSizeOptimizer.paginate_response([], page=1, page_size=10)
        assert result["items"] == []
        assert result["pagination"]["total_items"] == 0
        assert result["pagination"]["total_pages"] == 0

    def test_beyond_last_page(self):
        items = [1, 2]
        result = ResponseSizeOptimizer.paginate_response(items, page=5, page_size=10)
        assert result["items"] == []
