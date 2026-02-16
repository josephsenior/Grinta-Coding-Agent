"""Tests for backend.server.dependencies module."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestCheckHeaderAuth:
    def test_valid_key(self):
        from backend.server.dependencies import _check_header_auth

        assert _check_header_auth("my-secret-key", "my-secret-key") is True

    def test_invalid_key(self):
        from backend.server.dependencies import _check_header_auth

        assert _check_header_auth("wrong-key", "my-secret-key") is False

    def test_none_key(self):
        from backend.server.dependencies import _check_header_auth

        assert _check_header_auth(None, "my-secret-key") is False

    def test_empty_key(self):
        from backend.server.dependencies import _check_header_auth

        assert _check_header_auth("", "expected") is False


class TestCheckBearerAuth:
    def test_valid_bearer(self):
        from backend.server.dependencies import _check_bearer_auth

        request = MagicMock()
        request.headers = {"Authorization": "Bearer my-token"}
        assert _check_bearer_auth(request, "my-token") is True

    def test_invalid_bearer(self):
        from backend.server.dependencies import _check_bearer_auth

        request = MagicMock()
        request.headers = {"Authorization": "Bearer wrong-token"}
        assert _check_bearer_auth(request, "my-token") is False

    def test_no_authorization_header(self):
        from backend.server.dependencies import _check_bearer_auth

        request = MagicMock()
        request.headers = {}
        assert _check_bearer_auth(request, "my-token") is False

    def test_none_request(self):
        from backend.server.dependencies import _check_bearer_auth

        assert _check_bearer_auth(None, "my-token") is False

    def test_basic_scheme_rejected(self):
        from backend.server.dependencies import _check_bearer_auth

        request = MagicMock()
        request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        assert _check_bearer_auth(request, "my-token") is False


class TestCheckSessionApiKey:
    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="")
    def test_no_expected_key_passes(self, mock_get_key):
        from backend.server.dependencies import check_session_api_key

        request = MagicMock()
        # Should not raise
        check_session_api_key(request, None)

    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="secret123")
    def test_valid_header_key(self, mock_get_key):
        from backend.server.dependencies import check_session_api_key

        request = MagicMock()
        request.headers = {}
        check_session_api_key(request, "secret123")  # should not raise

    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="secret123")
    def test_valid_bearer_key(self, mock_get_key):
        from backend.server.dependencies import check_session_api_key

        request = MagicMock()
        request.headers = {"Authorization": "Bearer secret123"}
        check_session_api_key(request, None)  # header is None, but bearer matches

    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="secret123")
    def test_invalid_key_raises(self, mock_get_key):
        from backend.server.dependencies import check_session_api_key

        request = MagicMock()
        request.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            check_session_api_key(request, "wrong-key")
        assert exc_info.value.status_code == 401

    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="secret123")
    def test_missing_key_raises(self, mock_get_key):
        from backend.server.dependencies import check_session_api_key

        request = MagicMock()
        request.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            check_session_api_key(request, None)
        assert exc_info.value.status_code == 401


class TestGetDependencies:
    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="key123")
    def test_returns_dependency_when_key_set(self, mock_get_key):
        from backend.server.dependencies import get_dependencies

        deps = get_dependencies()
        assert len(deps) == 1

    @patch("backend.server.middleware.token_auth.get_session_api_key", return_value="")
    def test_returns_empty_when_no_key(self, mock_get_key):
        from backend.server.dependencies import get_dependencies

        deps = get_dependencies()
        assert len(deps) == 0
