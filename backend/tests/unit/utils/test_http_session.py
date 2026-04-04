"""Tests for backend.utils.http_session — HttpSession wrapper with close guard."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.utils.http_session import HttpSession, SessionClosedError

# ── HttpSession ────────────────────────────────────────────────────────


class TestHttpSession:
    """Test HttpSession wrapper around httpx.Client."""

    def test_creates_session(self):
        """Test creating new HTTP session."""
        session = HttpSession()
        assert session is not None
        assert session._is_closed is False

    def test_creates_session_with_headers(self):
        """Test creating session with default headers."""
        session = HttpSession(headers={'Authorization': 'Bearer token'})
        assert session.headers == {'Authorization': 'Bearer token'}

    def test_close_marks_session_closed(self):
        """Test close marks session as closed."""
        session = HttpSession()
        assert session._is_closed is False
        session.close()
        assert session._is_closed is True

    def test_request_after_close_raises_error(self):
        """Test request after close raises SessionClosedError."""
        session = HttpSession()
        session.close()

        with pytest.raises(SessionClosedError, match='closed'):
            session.request('GET', 'http://example.com')

    def test_get_after_close_raises_error(self):
        """Test GET request after close raises SessionClosedError."""
        session = HttpSession()
        session.close()

        with pytest.raises(SessionClosedError, match='closed'):
            session.get('http://example.com')

    def test_post_after_close_raises_error(self):
        """Test POST request after close raises SessionClosedError."""
        session = HttpSession()
        session.close()

        with pytest.raises(SessionClosedError, match='closed'):
            session.post('http://example.com', data={})

    def test_stream_after_close_raises_error(self):
        """Test stream after close raises SessionClosedError."""
        session = HttpSession()
        session.close()

        with pytest.raises(SessionClosedError, match='closed'):
            session.stream('GET', 'http://example.com')

    def test_request_merges_headers(self):
        """Test request merges default headers with request headers."""
        session = HttpSession(headers={'X-Default': 'value1'})

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.request('GET', 'http://example.com', headers={'X-Custom': 'value2'})

            call_args = mock_client.request.call_args
            merged_headers = call_args[1]['headers']
            assert merged_headers['X-Default'] == 'value1'
            assert merged_headers['X-Custom'] == 'value2'

    def test_request_headers_override_defaults(self):
        """Test request headers override default headers."""
        session = HttpSession(headers={'X-Header': 'default'})

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.request(
                'GET', 'http://example.com', headers={'X-Header': 'override'}
            )

            call_args = mock_client.request.call_args
            assert call_args[1]['headers']['X-Header'] == 'override'

    def test_get_delegates_to_request(self):
        """Test GET method delegates to request."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.get('http://example.com')

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == 'GET'

    def test_post_delegates_to_request(self):
        """Test POST method delegates to request."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.post('http://example.com', data={'key': 'value'})

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == 'POST'

    def test_patch_delegates_to_request(self):
        """Test PATCH method delegates to request."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.patch('http://example.com', data={'update': 'field'})

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == 'PATCH'

    def test_put_delegates_to_request(self):
        """Test PUT method delegates to request."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.put('http://example.com', data={'replace': 'all'})

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == 'PUT'

    def test_delete_delegates_to_request(self):
        """Test DELETE method delegates to request."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.delete('http://example.com')

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == 'DELETE'

    def test_options_delegates_to_request(self):
        """Test OPTIONS method delegates to request."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.options('http://example.com')

            mock_client.request.assert_called_once()
            call_args = mock_client.request.call_args
            assert call_args[0][0] == 'OPTIONS'

    def test_stream_merges_headers(self):
        """Test stream merges default headers."""
        session = HttpSession(headers={'X-Stream': 'header'})

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.stream.return_value = MagicMock()
            session.stream('GET', 'http://example.com')

            call_args = mock_client.stream.call_args
            assert call_args[1]['headers']['X-Stream'] == 'header'

    def test_request_without_headers(self):
        """Test request works when no headers provided."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()
            session.request('GET', 'http://example.com')

            mock_client.request.assert_called_once()

    def test_multiple_requests_before_close(self):
        """Test multiple requests work before closing."""
        session = HttpSession()

        with patch('backend.utils.http_session.CLIENT') as mock_client:
            mock_client.request.return_value = MagicMock()

            session.get('http://example.com/1')
            session.get('http://example.com/2')
            session.post('http://example.com/3', data={})

            assert mock_client.request.call_count == 3

    def test_close_is_idempotent(self):
        """Test calling close multiple times is safe."""
        session = HttpSession()
        session.close()
        session.close()  # Should not raise
        assert session._is_closed is True


# ── SessionClosedError ─────────────────────────────────────────────────


class TestSessionClosedError:
    """Test SessionClosedError exception."""

    def test_is_runtime_error(self):
        """Test SessionClosedError inherits from RuntimeError."""
        error = SessionClosedError('test message')
        assert isinstance(error, RuntimeError)

    def test_has_message(self):
        """Test error contains message."""
        error = SessionClosedError('session is closed')
        assert 'session is closed' in str(error)

    def test_can_be_raised_and_caught(self):
        """Test error can be raised and caught."""
        with pytest.raises(SessionClosedError) as exc_info:
            raise SessionClosedError('closed')
        assert 'closed' in str(exc_info.value)
