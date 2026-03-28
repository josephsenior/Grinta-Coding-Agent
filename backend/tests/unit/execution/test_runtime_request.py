"""Tests for backend.execution.utils.request module."""

from unittest.mock import MagicMock

import httpx
import pytest

from backend.execution.utils.request import (
    RequestHTTPError,
    is_retryable_error,
)


class TestRequestHTTPError:
    def test_basic_error(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request)
        err = RequestHTTPError("Server Error", request=request, response=response)
        assert "Server Error" in str(err)

    def test_error_with_detail(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request)
        err = RequestHTTPError(
            "Server Error",
            request=request,
            response=response,
            detail={"message": "overloaded"},
        )
        assert "Details:" in str(err)
        assert "overloaded" in str(err)

    def test_error_without_detail(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request)
        err = RequestHTTPError("Server Error", request=request, response=response)
        assert err.detail is None
        assert "Details:" not in str(err)

    def test_is_http_status_error(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request)
        err = RequestHTTPError("Server Error", request=request, response=response)
        assert isinstance(err, httpx.HTTPStatusError)


class TestIsRetryableError:
    def test_429_is_retryable(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(429, request=request)
        err = httpx.HTTPStatusError("Rate limited", request=request, response=response)
        assert is_retryable_error(err) is True

    def test_500_not_retryable(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request)
        err = httpx.HTTPStatusError("Server Error", request=request, response=response)
        assert is_retryable_error(err) is False

    def test_non_http_error_not_retryable(self):
        assert is_retryable_error(RuntimeError("something")) is False

    def test_none_not_retryable(self):
        assert is_retryable_error(None) is False

    def test_401_not_retryable(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(401, request=request)
        err = httpx.HTTPStatusError("Unauthorized", request=request, response=response)
        assert is_retryable_error(err) is False


class TestSendRequest:
    def test_successful_request(self):
        from backend.execution.utils.request import send_request

        mock_session = MagicMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_response

        result = send_request(mock_session, "GET", "http://example.com")
        assert result is mock_response
        mock_session.request.assert_called_once_with(
            "GET", "http://example.com", timeout=60
        )

    def test_custom_timeout(self):
        from backend.execution.utils.request import send_request

        mock_session = MagicMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_response

        send_request(mock_session, "POST", "http://example.com/api", timeout=120)
        mock_session.request.assert_called_once_with(
            "POST", "http://example.com/api", timeout=120
        )

    def test_http_error_raises_request_http_error(self):
        from backend.execution.utils.request import send_request

        mock_session = MagicMock()
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(400, request=request, json={"detail": "bad input"})
        mock_session.request.return_value = response

        with pytest.raises(RequestHTTPError) as exc_info:
            send_request(mock_session, "GET", "http://example.com")
        assert exc_info.value.detail == "bad input"

    def test_http_error_non_json_response(self):
        from backend.execution.utils.request import send_request

        mock_session = MagicMock()
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(500, request=request, text="Internal Error")
        mock_session.request.return_value = response

        with pytest.raises(RequestHTTPError) as exc_info:
            send_request(mock_session, "GET", "http://example.com")
        assert exc_info.value.detail is None
