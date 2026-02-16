"""Tests for backend.server.middleware.token_auth — SimpleTokenAuthMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.server.middleware.token_auth import SimpleTokenAuthMiddleware

FAKE_KEY = "test-secret-key-1234"


def _make_app():
    return MagicMock()


def _make_request(method="GET", path="/api/test", headers=None):
    req = MagicMock()
    req.method = method
    req.url.path = path
    req.headers = headers or {}
    return req


@pytest.fixture(autouse=True)
def _mock_key():
    with patch(
        "backend.server.middleware.token_auth.get_session_api_key",
        return_value=FAKE_KEY,
    ):
        yield


# --------------- Public Paths ---------------

class TestPublicPaths:
    @pytest.mark.asyncio
    async def test_options_allowed(self):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(method="OPTIONS", path="/api/private")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await mw.dispatch(req, call_next)
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/auth/login",
            "/docs",
            "/openapi.json",
            "/favicon.ico",
            "/alive",
            "/api/health/live",
            "/api/health/ready",
            "/assets/main.js",
            "/locales/en.json",
            "/mcp/sse",
            "/static/style.css",
        ],
    )
    async def test_public_paths_no_auth(self, path):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(path=path)
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await mw.dispatch(req, call_next)
        call_next.assert_awaited_once()


# --------------- Authentication ---------------

class TestAuth:
    @pytest.mark.asyncio
    async def test_valid_session_api_key_header(self):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(
            path="/api/private",
            headers={"X-Session-API-Key": FAKE_KEY},
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await mw.dispatch(req, call_next)
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_valid_bearer_token(self):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(
            path="/api/private",
            headers={"Authorization": f"Bearer {FAKE_KEY}"},
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await mw.dispatch(req, call_next)
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(path="/api/private")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_key_returns_401(self):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(
            path="/api/private",
            headers={"X-Session-API-Key": "wrong-key"},
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_bearer_returns_401(self):
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(
            path="/api/private",
            headers={"Authorization": "Bearer wrong-token"},
        )
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_monitoring_not_public(self):
        """Ensure /api/monitoring/ requires auth."""
        mw = SimpleTokenAuthMiddleware(_make_app())
        req = _make_request(path="/api/monitoring/metrics")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 401
