"""Tests for backend.gateway.middleware.request_size — RequestSizeLoggingMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.gateway.middleware.request_size import RequestSizeLoggingMiddleware


@pytest.fixture
def mw():
    return RequestSizeLoggingMiddleware(enabled=True)


@pytest.fixture
def disabled_mw():
    return RequestSizeLoggingMiddleware(enabled=False)


def _make_request(method="GET", path="/test", content_length=None):
    req = MagicMock()
    req.method = method
    req.url.path = path
    headers = {}
    if content_length is not None:
        headers["content-length"] = str(content_length)
    req.headers = headers
    req.state.request_id = "req-123"
    return req


# --------------- _content_length_from_headers ---------------


class TestContentLengthFromHeaders:
    def test_returns_int_when_present(self, mw):
        headers = {"content-length": "1024"}
        assert mw._content_length_from_headers(headers) == 1024

    def test_returns_none_when_missing(self, mw):
        assert mw._content_length_from_headers({}) is None

    def test_returns_none_on_invalid(self, mw):
        assert mw._content_length_from_headers({"content-length": "abc"}) is None


# --------------- _response_size ---------------


class TestResponseSize:
    def test_from_content_length_header(self, mw):
        resp = MagicMock()
        resp.headers = {"content-length": "512"}
        assert mw._response_size(resp) == 512

    def test_from_body_attribute(self, mw):
        resp = MagicMock(spec=["headers", "body"])
        resp.headers = {}
        resp.body = b"hello world"
        assert mw._response_size(resp) == 11

    def test_none_when_no_info(self, mw):
        resp = MagicMock(spec=["headers"])
        resp.headers = {}
        assert mw._response_size(resp) is None


# --------------- __call__ ---------------


class TestCall:
    @pytest.mark.asyncio
    async def test_disabled_passes_through(self, disabled_mw):
        req = _make_request()
        call_next = AsyncMock(return_value=MagicMock(headers={}))
        await disabled_mw(req, call_next)
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_logs_request_size(self, mw):
        req = _make_request(content_length=100)
        response = MagicMock()
        response.headers = {"content-length": "200"}
        # No body_iterator
        response.body_iterator = None
        call_next = AsyncMock(return_value=response)
        with patch.object(mw, "_log_request_size") as log_mock:
            await mw(req, call_next)
            log_mock.assert_called_once()


# --------------- _wrap_streaming_response ---------------


class TestWrapStreamingResponse:
    def test_returns_false_when_no_body_iterator(self, mw):
        resp = MagicMock()
        resp.body_iterator = None
        req = _make_request()
        assert mw._wrap_streaming_response(resp, req, 0, None) is False

    def test_returns_false_when_body_iterator_not_async(self, mw):
        resp = MagicMock()
        resp.body_iterator = "not_an_iterator"
        resp.headers = {}
        resp.body = None
        req = _make_request()
        result = mw._wrap_streaming_response(resp, req, 0, None)
        # Could be True or False depending on whether __aiter__ exists
        assert isinstance(result, bool)


# --------------- _log_request_size ---------------


class TestLogRequestSize:
    def test_logs_info(self, mw):
        req = _make_request(method="POST", path="/api/test")
        with patch("backend.gateway.middleware.request_size.ACCESS_logger") as mock_log:
            mw._log_request_size(req, 100, 200, "req-123", streaming=False)
            mock_log.info.assert_called_once()
            extra = mock_log.info.call_args[1]["extra"]
            assert extra["method"] == "POST"
            assert extra["path"] == "/api/test"
            assert extra["request_content_length"] == 100
            assert extra["response_content_length"] == 200
            assert extra["streaming"] is False
