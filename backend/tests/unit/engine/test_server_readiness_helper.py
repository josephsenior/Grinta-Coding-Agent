"""Tests for backend.engine.tools.server_readiness_helper module.

Targets 0% coverage (38 statements).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.engine.tools.server_readiness_helper import (
    check_server_ready,
    create_safe_navigation_browser_code,
    safe_goto_localhost,
    safe_navigate_to_url,
    wait_for_server_ready,
)


# -----------------------------------------------------------
# wait_for_server_ready
# -----------------------------------------------------------


class TestWaitForServerReady:
    @patch("backend.engine.tools.server_readiness_helper.time")
    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_returns_true_when_server_responds(self, mock_requests, mock_time):
        mock_time.time.side_effect = [0, 0, 1]
        resp = MagicMock(status_code=200)
        mock_requests.head.return_value = resp
        mock_requests.exceptions.RequestException = Exception

        assert wait_for_server_ready("http://localhost:3000", max_wait_time=5) is True

    @patch("backend.engine.tools.server_readiness_helper.time")
    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_returns_false_on_timeout(self, mock_requests, mock_time):
        """time.time() returns increasing values that exceed max_wait_time."""
        mock_time.time.side_effect = [0, 0, 100]
        mock_requests.head.side_effect = Exception("conn refused")
        mock_requests.exceptions.RequestException = Exception

        assert wait_for_server_ready("http://localhost:3000", max_wait_time=5) is False

    @patch("backend.engine.tools.server_readiness_helper.time")
    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_server_error_keeps_trying(self, mock_requests, mock_time):
        """Status 500 is treated as not-ready, keeps trying."""
        mock_time.time.side_effect = [0, 0, 0, 1, 1, 100]
        mock_time.sleep = MagicMock()
        resp500 = MagicMock(status_code=500)
        mock_requests.head.return_value = resp500
        mock_requests.exceptions.RequestException = Exception

        assert wait_for_server_ready("http://localhost:3000", max_wait_time=5) is False

    @patch("backend.engine.tools.server_readiness_helper.time")
    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_accepts_non_200_below_500(self, mock_requests, mock_time):
        """Any status_code < 500 is considered ready."""
        mock_time.time.side_effect = [0, 0, 1]
        resp = MagicMock(status_code=302)
        mock_requests.head.return_value = resp
        mock_requests.exceptions.RequestException = Exception

        assert wait_for_server_ready("http://localhost:3000") is True


# -----------------------------------------------------------
# check_server_ready
# -----------------------------------------------------------


class TestCheckServerReady:
    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_returns_true_when_healthy(self, mock_requests):
        resp = MagicMock(status_code=200)
        mock_requests.head.return_value = resp
        mock_requests.exceptions.RequestException = Exception
        assert check_server_ready("http://localhost:8080") is True

    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_returns_false_on_500(self, mock_requests):
        resp = MagicMock(status_code=500)
        mock_requests.head.return_value = resp
        mock_requests.exceptions.RequestException = Exception
        assert check_server_ready("http://localhost:8080") is False

    @patch("backend.engine.tools.server_readiness_helper.requests")
    def test_returns_false_on_exception(self, mock_requests):
        mock_requests.head.side_effect = Exception("conn")
        mock_requests.exceptions.RequestException = Exception
        assert check_server_ready("http://localhost:8080") is False


# -----------------------------------------------------------
# safe_goto_localhost
# -----------------------------------------------------------


class TestSafeGotoLocalhost:
    def test_non_localhost_returns_plain_goto(self):
        result = safe_goto_localhost("https://example.com")
        assert result == "goto('https://example.com')"

    @patch(
        "backend.engine.tools.server_readiness_helper.safe_navigate_to_url"
    )
    def test_localhost_calls_safe_navigate(self, mock_sn):
        mock_sn.return_value = "safe_code"
        result = safe_goto_localhost("http://localhost:3000")
        assert result == "safe_code"
        mock_sn.assert_called_once()

    @patch(
        "backend.engine.tools.server_readiness_helper.safe_navigate_to_url"
    )
    def test_127_0_0_1_calls_safe_navigate(self, mock_sn):
        mock_sn.return_value = "safe_code"
        result = safe_goto_localhost("http://127.0.0.1:8080")
        assert result == "safe_code"


# -----------------------------------------------------------
# safe_navigate_to_url
# -----------------------------------------------------------


class TestSafeNavigateToUrl:
    def test_non_http_returns_original(self):
        result = safe_navigate_to_url("code", "file:///tmp/foo")
        assert result == "code"

    def test_http_returns_wrapped_code(self):
        result = safe_navigate_to_url("goto('http://x')", "http://x")
        assert "wait_for_server_ready" in result
        assert "goto('http://x')" in result

    def test_contains_url_in_output(self):
        result = safe_navigate_to_url("browser_code", "https://mysite.com/path")
        assert "mysite.com" in result


# -----------------------------------------------------------
# create_safe_navigation_browser_code
# -----------------------------------------------------------


class TestCreateSafeNavigationBrowserCode:
    def test_basic_url(self):
        result = create_safe_navigation_browser_code("http://localhost:3000")
        assert "goto" in result
        assert "wait_for_server_ready" in result

    def test_with_additional_actions(self):
        result = create_safe_navigation_browser_code(
            "http://localhost:3000", additional_actions="click('#btn')"
        )
        assert "click('#btn')" in result
