"""Tests for backend.server.middleware.request_limits — RequestSizeLimiter."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.server.middleware.request_limits import RequestSizeLimiter


def _make_app():
    return MagicMock()


def _make_request(method="POST", path="/api/test", content_length=None):
    req = MagicMock()
    req.method = method
    req.url.path = path
    headers = {}
    if content_length is not None:
        headers["content-length"] = str(content_length)
    req.headers = headers
    return req


# --------------- Initialization ---------------

class TestInit:
    def test_default_max_size(self):
        limiter = RequestSizeLimiter(_make_app(), enabled=False)
        # Default is 10MB
        assert limiter.max_request_size == 10 * 1024 * 1024

    def test_custom_max_size(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=5000, enabled=False)
        assert limiter.max_request_size == 5000

    def test_env_var_override(self):
        with patch.dict(os.environ, {"REQUEST_SIZE_LIMIT_MB": "20"}):
            limiter = RequestSizeLimiter(_make_app(), enabled=False)
            assert limiter.max_request_size == 20 * 1024 * 1024


# --------------- dispatch ---------------

class TestDispatch:
    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        limiter = RequestSizeLimiter(_make_app(), enabled=False)
        req = _make_request(content_length=999999999)
        call_next = AsyncMock(return_value=MagicMock())
        await limiter.dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_get_request_passes(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="GET", content_length=999999)
        call_next = AsyncMock(return_value=MagicMock())
        await limiter.dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_small_request_passes(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=1000, enabled=True)
        req = _make_request(method="POST", content_length=500)
        call_next = AsyncMock(return_value=MagicMock())
        await limiter.dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_large_request_rejected_413(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="POST", content_length=500)
        call_next = AsyncMock(return_value=MagicMock())
        with pytest.raises(HTTPException) as exc_info:
            await limiter.dispatch(req, call_next)
        assert exc_info.value.status_code == 413

    @pytest.mark.asyncio
    async def test_put_also_checked(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="PUT", content_length=500)
        call_next = AsyncMock(return_value=MagicMock())
        with pytest.raises(HTTPException) as exc_info:
            await limiter.dispatch(req, call_next)
        assert exc_info.value.status_code == 413

    @pytest.mark.asyncio
    async def test_patch_also_checked(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="PATCH", content_length=500)
        call_next = AsyncMock(return_value=MagicMock())
        with pytest.raises(HTTPException) as exc_info:
            await limiter.dispatch(req, call_next)
        assert exc_info.value.status_code == 413

    @pytest.mark.asyncio
    async def test_missing_content_length_passes(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="POST")
        call_next = AsyncMock(return_value=MagicMock())
        await limiter.dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_invalid_content_length_passes(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="POST")
        req.headers["content-length"] = "not-a-number"
        call_next = AsyncMock(return_value=MagicMock())
        await limiter.dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)

    @pytest.mark.asyncio
    async def test_delete_not_checked(self):
        limiter = RequestSizeLimiter(_make_app(), max_request_size=100, enabled=True)
        req = _make_request(method="DELETE", content_length=999999)
        call_next = AsyncMock(return_value=MagicMock())
        await limiter.dispatch(req, call_next)
        call_next.assert_awaited_once_with(req)
