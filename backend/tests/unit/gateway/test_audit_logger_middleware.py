"""Tests for backend.gateway.middleware.audit_logger module.

Targets the 20.8% (61 missed lines) coverage gap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.gateway.middleware.audit_logger import (
    AUDIT_OPERATIONS,
    AuditLoggerMiddleware,
)


def _make_middleware():
    """Create a middleware instance without an actual Starlette app."""
    m = AuditLoggerMiddleware.__new__(AuditLoggerMiddleware)
    return m


# ------------------------------------------------------------------
# _matches_pattern
# ------------------------------------------------------------------
class TestMatchesPattern:
    def test_exact_match(self):
        m = _make_middleware()
        assert (
            m._matches_pattern("POST /api/v1/settings", "POST /api/v1/settings") is True
        )

    def test_method_mismatch(self):
        m = _make_middleware()
        assert (
            m._matches_pattern("GET /api/v1/settings", "POST /api/v1/settings") is False
        )

    def test_path_mismatch(self):
        m = _make_middleware()
        assert (
            m._matches_pattern("POST /api/v1/other", "POST /api/v1/settings") is False
        )

    def test_incomplete_operation(self):
        m = _make_middleware()
        assert m._matches_pattern("POST", "POST /api/v1/settings") is False

    def test_incomplete_pattern(self):
        m = _make_middleware()
        assert m._matches_pattern("POST /x", "POST") is False


# ------------------------------------------------------------------
# _path_matches
# ------------------------------------------------------------------
class TestPathMatches:
    def test_exact_path(self):
        m = _make_middleware()
        assert m._path_matches("/api/v1/settings", "/api/v1/settings") is True

    def test_param_placeholder_matches(self):
        m = _make_middleware()
        assert (
            m._path_matches(
                "/api/v1/conversations/abc123", "/api/v1/conversations/{id}"
            )
            is True
        )

    def test_different_lengths(self):
        m = _make_middleware()
        assert m._path_matches("/api/v1/a/b", "/api/v1/a") is False

    def test_literal_mismatch(self):
        m = _make_middleware()
        assert m._path_matches("/api/v1/secrets", "/api/v1/settings") is False

    def test_multiple_params(self):
        m = _make_middleware()
        assert m._path_matches("/a/X/c/Y", "/a/{p1}/c/{p2}") is True


# ------------------------------------------------------------------
# _get_client_ip
# ------------------------------------------------------------------
class TestGetClientIP:
    def test_x_forwarded_for(self):
        m = _make_middleware()
        req = MagicMock()
        req.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        assert m._get_client_ip(req) == "1.2.3.4"

    def test_x_real_ip(self):
        m = _make_middleware()
        req = MagicMock()
        req.headers = MagicMock()
        req.headers.get.side_effect = lambda k, d=None: (
            None if k == "X-Forwarded-For" else "10.0.0.1" if k == "X-Real-IP" else d
        )
        assert m._get_client_ip(req) == "10.0.0.1"

    def test_direct_client(self):
        m = _make_middleware()
        req = MagicMock()
        req.headers = MagicMock()
        req.headers.get.return_value = None
        req.client = MagicMock()
        req.client.host = "192.168.1.1"
        assert m._get_client_ip(req) == "192.168.1.1"

    def test_unknown_ip(self):
        m = _make_middleware()
        req = MagicMock()
        req.headers = MagicMock()
        req.headers.get.return_value = None
        req.client = None
        assert m._get_client_ip(req) == "unknown"


# ------------------------------------------------------------------
# _extract_conversation_id
# ------------------------------------------------------------------
class TestExtractConversationId:
    def test_with_conversation_id(self):
        m = _make_middleware()
        result = m._extract_conversation_id("/api/v1/conversations/abc123")
        assert result == "abc123"

    def test_no_conversation_in_path(self):
        m = _make_middleware()
        result = m._extract_conversation_id("/api/v1/settings")
        assert result is None

    def test_conversations_at_end(self):
        m = _make_middleware()
        result = m._extract_conversation_id("/api/v1/conversations")
        assert result is None


# ------------------------------------------------------------------
# AUDIT_OPERATIONS
# ------------------------------------------------------------------
class TestAuditOperations:
    def test_expected_operations(self):
        assert "POST /api/v1/settings" in AUDIT_OPERATIONS
        assert "DELETE /api/v1/conversations" in AUDIT_OPERATIONS
        assert "POST /api/v1/secrets" in AUDIT_OPERATIONS

    def test_operations_are_strings(self):
        for k, v in AUDIT_OPERATIONS.items():
            assert isinstance(k, str)
            assert isinstance(v, str)


# ------------------------------------------------------------------
# dispatch (integration)
# ------------------------------------------------------------------
class TestDispatch:
    @pytest.mark.asyncio
    async def test_non_audit_operation(self):
        m = _make_middleware()
        req = MagicMock()
        req.method = "GET"
        req.url.path = "/api/v1/health"
        resp = MagicMock()
        resp.status_code = 200
        call_next = AsyncMock(return_value=resp)

        result = await m.dispatch(req, call_next)
        assert result is resp

    @pytest.mark.asyncio
    async def test_audit_operation_logged(self):
        m = _make_middleware()
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/v1/settings"
        req.headers = MagicMock()
        _header_data = {"user-agent": "test", "X-User-ID": "user1"}
        req.headers.get.side_effect = lambda k, d="unknown": _header_data.get(k, d)
        req.state = MagicMock(spec=[])  # no user_id attr
        req.client = MagicMock()
        req.client.host = "127.0.0.1"

        resp = MagicMock()
        resp.status_code = 200
        call_next = AsyncMock(return_value=resp)

        with patch("backend.gateway.middleware.audit_logger.logger") as mock_logger:
            result = await m.dispatch(req, call_next)
        assert result is resp
        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_not_logged_on_error_status(self):
        m = _make_middleware()
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/api/v1/settings"

        resp = MagicMock()
        resp.status_code = 500  # non-2xx
        call_next = AsyncMock(return_value=resp)

        with patch("backend.gateway.middleware.audit_logger.logger") as mock_logger:
            result = await m.dispatch(req, call_next)
        assert result is resp
        mock_logger.info.assert_not_called()
