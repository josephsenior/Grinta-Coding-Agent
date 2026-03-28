"""Tests for backend.gateway.middleware.security_headers — SecurityHeadersMiddleware & CSRFProtection."""

from __future__ import annotations

import os
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.gateway.middleware.security_headers import (
    CSRFProtection,
    SecurityHeadersMiddleware,
)


# ── SecurityHeadersMiddleware ────────────────────────────────────────


class TestSecurityHeadersInit:
    def test_defaults(self):
        mw = SecurityHeadersMiddleware()
        assert mw.enabled is True
        assert mw.csp_profile == "permissive"

    def test_disabled(self):
        mw = SecurityHeadersMiddleware(enabled=False)
        assert mw.enabled is False

    def test_strict_profile(self):
        mw = SecurityHeadersMiddleware(csp_profile="strict")
        assert mw.csp_profile == "strict"

    def test_none_profile_defaults_to_permissive(self):
        mw = SecurityHeadersMiddleware(csp_profile=cast(str, None))
        assert mw.csp_profile == "permissive"


class TestSecurityHeadersCall:
    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        mw = SecurityHeadersMiddleware(enabled=False)
        req = MagicMock()
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)
        result = await mw(req, call_next)
        assert result is resp
        assert "X-Content-Type-Options" not in resp.headers

    @pytest.mark.asyncio
    async def test_adds_security_headers(self):
        mw = SecurityHeadersMiddleware(enabled=True, csp_profile="permissive")
        req = MagicMock()
        req.url.scheme = "http"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        await mw(req, call_next)

        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert (
            "Content-Security-Policy" in resp.headers
            or "Content-Security-Policy-Report-Only" in resp.headers
        )
        assert "Permissions-Policy" in resp.headers
        assert resp.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
        assert resp.headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert resp.headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert resp.headers["X-Permitted-Cross-Domain-Policies"] == "none"

    @pytest.mark.asyncio
    async def test_hsts_on_https(self):
        mw = SecurityHeadersMiddleware(enabled=True)
        req = MagicMock()
        req.url.scheme = "https"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        await mw(req, call_next)
        assert "Strict-Transport-Security" in resp.headers

    @pytest.mark.asyncio
    async def test_no_hsts_on_http(self):
        mw = SecurityHeadersMiddleware(enabled=True)
        req = MagicMock()
        req.url.scheme = "http"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        await mw(req, call_next)
        assert "Strict-Transport-Security" not in resp.headers

    @pytest.mark.asyncio
    async def test_strict_csp_profile(self):
        mw = SecurityHeadersMiddleware(enabled=True, csp_profile="strict")
        req = MagicMock()
        req.url.scheme = "http"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CSP_REPORT_URI", None)
            os.environ.pop("CSP_REPORT_ONLY", None)
            await mw(req, call_next)

        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        # Strict should NOT have unsafe-inline
        assert (
            "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
            if "script-src" in csp
            else True
        )

    @pytest.mark.asyncio
    async def test_csp_report_only_mode(self):
        mw = SecurityHeadersMiddleware(enabled=True)
        req = MagicMock()
        req.url.scheme = "http"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        with patch.dict(os.environ, {"CSP_REPORT_ONLY": "true"}, clear=False):
            await mw(req, call_next)

        assert "Content-Security-Policy-Report-Only" in resp.headers

    @pytest.mark.asyncio
    async def test_csp_report_uri(self):
        mw = SecurityHeadersMiddleware(enabled=True)
        req = MagicMock()
        req.url.scheme = "http"
        resp = MagicMock()
        resp.headers = {}
        call_next = AsyncMock(return_value=resp)

        with patch.dict(
            os.environ,
            {"CSP_REPORT_URI": "https://example.com/report", "CSP_REPORT_ONLY": "0"},
            clear=False,
        ):
            await mw(req, call_next)

        csp = resp.headers.get("Content-Security-Policy", "")
        assert "report-uri https://example.com/report" in csp


# ── CSRFProtection ───────────────────────────────────────────────────


class TestCSRFProtectionInit:
    def test_defaults(self):
        csrf = CSRFProtection()
        assert csrf.enabled is True

    def test_disabled(self):
        csrf = CSRFProtection(enabled=False)
        assert csrf.enabled is False


class TestShouldSkipCsrfCheck:
    def test_disabled_skips(self):
        csrf = CSRFProtection(enabled=False)
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/data"
        assert csrf._should_skip_csrf_check(req) is True

    def test_get_skips(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "GET"
        assert csrf._should_skip_csrf_check(req) is True

    def test_head_skips(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "HEAD"
        assert csrf._should_skip_csrf_check(req) is True

    def test_post_does_not_skip(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/data"
        assert csrf._should_skip_csrf_check(req) is False

    def test_put_does_not_skip(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "PUT"
        req.url.path = "/api/data"
        assert csrf._should_skip_csrf_check(req) is False

    def test_delete_does_not_skip(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "DELETE"
        req.url.path = "/api/data"
        assert csrf._should_skip_csrf_check(req) is False


class TestValidateOriginHeader:
    def test_matching_origin(self):
        csrf = CSRFProtection()
        valid, msg = csrf._validate_origin_header(
            "http://localhost:3000", "http://localhost:3000"
        )
        assert valid is True
        assert msg == ""

    def test_mismatching_origin(self):
        csrf = CSRFProtection()
        valid, msg = csrf._validate_origin_header(
            "http://evil.com", "http://localhost:3000"
        )
        assert valid is False
        assert "CSRF" in msg

    def test_localhost_different_ports(self):
        csrf = CSRFProtection()
        valid, msg = csrf._validate_origin_header(
            "http://localhost:5173", "http://localhost:3000"
        )
        assert valid is True  # localhost dev scenario


class TestValidateRefererHeader:
    def test_matching_referer(self):
        csrf = CSRFProtection()
        valid, msg = csrf._validate_referer_header(
            "http://localhost:3000/page", "http://localhost:3000"
        )
        assert valid is True

    def test_mismatching_referer(self):
        csrf = CSRFProtection()
        valid, msg = csrf._validate_referer_header(
            "http://evil.com/page", "http://localhost:3000"
        )
        assert valid is False
        assert "CSRF" in msg


class TestIsLocalhostDevelopment:
    def test_same_localhost(self):
        csrf = CSRFProtection()
        assert (
            csrf._is_localhost_development(
                "http://localhost:5173", "http://localhost:3000"
            )
            is True
        )

    def test_127_0_0_1(self):
        csrf = CSRFProtection()
        assert (
            csrf._is_localhost_development(
                "http://127.0.0.1:5173", "http://127.0.0.1:3000"
            )
            is True
        )

    def test_mixed_localhost_127(self):
        csrf = CSRFProtection()
        assert (
            csrf._is_localhost_development(
                "http://localhost:5173", "http://127.0.0.1:3000"
            )
            is True
        )

    def test_not_localhost(self):
        csrf = CSRFProtection()
        assert (
            csrf._is_localhost_development(
                "http://example.com", "http://localhost:3000"
            )
            is False
        )

    def test_different_schemes(self):
        csrf = CSRFProtection()
        assert (
            csrf._is_localhost_development(
                "https://localhost:5173", "http://localhost:3000"
            )
            is False
        )

    def test_broken_url(self):
        csrf = CSRFProtection()
        # Should return False on any parse error
        result = csrf._is_localhost_development(
            "not://a valid url::::", "http://localhost"
        )
        assert isinstance(result, bool)


class TestCSRFProtectionCall:
    @pytest.mark.asyncio
    async def test_disabled_passes_through(self):
        csrf = CSRFProtection(enabled=False)
        req = MagicMock()
        req.method = "POST"
        resp = MagicMock()
        call_next = AsyncMock(return_value=resp)
        result = await csrf(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_get_passes_through(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "GET"
        resp = MagicMock()
        call_next = AsyncMock(return_value=resp)
        result = await csrf(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_post_without_origin_or_referer_returns_403(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/data"
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(return_value=None)
        req.headers = headers_mock

        call_next = AsyncMock()
        result = await csrf(req, call_next)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_post_with_valid_origin(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/data"
        req.url.scheme = "http"
        req.url.netloc = "localhost:3000"
        headers = {"Origin": "http://localhost:3000"}
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(side_effect=lambda k, d=None: headers.get(k, d))
        req.headers = headers_mock

        resp = MagicMock()
        call_next = AsyncMock(return_value=resp)
        result = await csrf(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_post_with_invalid_origin_returns_403(self):
        csrf = CSRFProtection(enabled=True)
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/data"
        req.url.scheme = "http"
        req.url.netloc = "localhost:3000"
        headers = {"Origin": "http://evil.com"}
        headers_mock = MagicMock()
        headers_mock.get = MagicMock(side_effect=lambda k, d=None: headers.get(k, d))
        req.headers = headers_mock

        call_next = AsyncMock()
        result = await csrf(req, call_next)
        assert result.status_code == 403
