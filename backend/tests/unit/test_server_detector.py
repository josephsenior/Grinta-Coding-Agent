"""Tests for backend.runtime.utils.server_detector — extract_port_from_output, is_port_listening."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from backend.runtime.utils.server_detector import (
    DetectedServer,
    extract_port_from_output,
    is_port_listening,
)


# ---------------------------------------------------------------------------
# DetectedServer dataclass
# ---------------------------------------------------------------------------

class TestDetectedServer:
    """Tests for the DetectedServer dataclass."""

    def test_basic_creation(self):
        ds = DetectedServer(
            port=3000, url="http://localhost:3000",
            protocol="http", health_status="healthy",
        )
        assert ds.port == 3000
        assert ds.url == "http://localhost:3000"
        assert ds.protocol == "http"
        assert ds.health_status == "healthy"
        assert ds.command_hint is None

    def test_with_command_hint(self):
        ds = DetectedServer(
            port=8080, url="http://localhost:8080",
            protocol="http", health_status="unknown",
            command_hint="python -m http.server 8080",
        )
        assert ds.command_hint == "python -m http.server 8080"


# ---------------------------------------------------------------------------
# extract_port_from_output
# ---------------------------------------------------------------------------

class TestExtractPortFromOutput:
    """Tests for extract_port_from_output."""

    def test_vite_server(self):
        output = "  VITE v5.0.0  ready in 300ms\n\n  ➜  Local:   http://localhost:5173/\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, protocol, line = result
        assert port == 5173

    def test_express_server(self):
        output = "Express listening on port 3000\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 3000

    def test_django_server(self):
        output = "Starting development server at http://127.0.0.1:8000/\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 8000

    def test_flask_server(self):
        output = " * Running on http://127.0.0.1:5000\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 5000

    def test_python_http_server(self):
        output = "Serving HTTP on 0.0.0.0 port 8080\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 8080

    def test_nextjs_server(self):
        output = "ready started server on 0.0.0.0:3000, url: http://localhost:3000\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 3000

    def test_generic_localhost_url(self):
        output = "Server available at http://localhost:4200\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 4200

    def test_no_server_detected(self):
        output = "Compiling...\nDone.\nAll tests passed.\n"
        result = extract_port_from_output(output)
        assert result is None

    def test_empty_output(self):
        result = extract_port_from_output("")
        assert result is None

    def test_system_port_rejected(self):
        """Ports below 1024 should be rejected."""
        output = "Server running at http://localhost:80\n"
        result = extract_port_from_output(output)
        assert result is None

    def test_webpack_dev_server(self):
        output = "Project is running at http://localhost:8080/\n"
        result = extract_port_from_output(output)
        assert result is not None
        port, _, _ = result
        assert port == 8080


# ---------------------------------------------------------------------------
# is_port_listening
# ---------------------------------------------------------------------------

class TestIsPortListening:
    """Tests for is_port_listening."""

    @patch("backend.runtime.utils.server_detector.socket.socket")
    def test_port_listening(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0  # success
        assert is_port_listening(8080) is True
        mock_sock.close.assert_called_once()

    @patch("backend.runtime.utils.server_detector.socket.socket")
    def test_port_not_listening(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        mock_sock.connect_ex.return_value = 1  # failure
        assert is_port_listening(8080) is False
        mock_sock.close.assert_called_once()

    @patch("backend.runtime.utils.server_detector.socket.socket")
    def test_port_os_error(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock
        mock_sock.connect_ex.side_effect = OSError("Network error")
        assert is_port_listening(8080) is False
        mock_sock.close.assert_called_once()
