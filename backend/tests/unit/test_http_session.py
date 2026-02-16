"""Tests for backend.utils.http_session."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.utils.http_session import HttpSession, SessionClosedError


class TestHttpSessionInit:
    def test_defaults(self):
        s = HttpSession()
        assert s._is_closed is False
        assert s.headers == {}

    def test_custom_headers(self):
        s = HttpSession(headers={"X-Foo": "bar"})
        assert s.headers["X-Foo"] == "bar"


class TestAssertOpen:
    def test_open_session_does_not_raise(self):
        s = HttpSession()
        s._assert_open()  # no exception

    def test_closed_session_raises(self):
        s = HttpSession()
        s.close()
        with pytest.raises(SessionClosedError, match="closed"):
            s._assert_open()


class TestClose:
    def test_close_sets_flag(self):
        s = HttpSession()
        s.close()
        assert s._is_closed is True

    def test_double_close_no_error(self):
        s = HttpSession()
        s.close()
        s.close()  # idempotent


class TestMergedHeaders:
    def test_merges_defaults_with_call_headers(self):
        s = HttpSession(headers={"Authorization": "Bearer tok"})
        kwargs: dict = {"headers": {"X-Custom": "yes"}}
        result = s._merged_headers(kwargs)
        assert result["headers"]["Authorization"] == "Bearer tok"
        assert result["headers"]["X-Custom"] == "yes"

    def test_call_headers_override_defaults(self):
        s = HttpSession(headers={"Authorization": "old"})
        kwargs: dict = {"headers": {"Authorization": "new"}}
        result = s._merged_headers(kwargs)
        assert result["headers"]["Authorization"] == "new"

    def test_no_headers_in_kwargs(self):
        s = HttpSession(headers={"A": "1"})
        kwargs: dict = {}
        result = s._merged_headers(kwargs)
        assert result["headers"]["A"] == "1"


class TestRequestAfterClose:
    def test_request_raises_after_close(self):
        s = HttpSession()
        s.close()
        with pytest.raises(SessionClosedError):
            s.request("GET", "http://localhost")

    def test_stream_raises_after_close(self):
        s = HttpSession()
        s.close()
        with pytest.raises(SessionClosedError):
            s.stream("GET", "http://localhost")

    def test_get_raises_after_close(self):
        s = HttpSession()
        s.close()
        with pytest.raises(SessionClosedError):
            s.get("http://localhost")

    def test_post_raises_after_close(self):
        s = HttpSession()
        s.close()
        with pytest.raises(SessionClosedError):
            s.post("http://localhost")


class TestShortcutMethods:
    """Verify shortcut methods delegate to request()."""

    @patch.object(HttpSession, "request", return_value=MagicMock())
    def test_get_delegates(self, mock_req):
        s = HttpSession()
        s.get("http://example.com")
        mock_req.assert_called_once_with("GET", "http://example.com")

    @patch.object(HttpSession, "request", return_value=MagicMock())
    def test_put_delegates(self, mock_req):
        s = HttpSession()
        s.put("http://example.com", json={"a": 1})
        mock_req.assert_called_once_with("PUT", "http://example.com", json={"a": 1})

    @patch.object(HttpSession, "request", return_value=MagicMock())
    def test_patch_delegates(self, mock_req):
        s = HttpSession()
        s.patch("http://example.com")
        mock_req.assert_called_once_with("PATCH", "http://example.com")

    @patch.object(HttpSession, "request", return_value=MagicMock())
    def test_delete_delegates(self, mock_req):
        s = HttpSession()
        s.delete("http://example.com")
        mock_req.assert_called_once_with("DELETE", "http://example.com")

    @patch.object(HttpSession, "request", return_value=MagicMock())
    def test_options_delegates(self, mock_req):
        s = HttpSession()
        s.options("http://example.com")
        mock_req.assert_called_once_with("OPTIONS", "http://example.com")
