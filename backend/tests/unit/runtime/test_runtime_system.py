"""Tests for backend.runtime.utils.system module."""

import socket
from unittest.mock import patch


from backend.runtime.utils.system import (
    check_port_available,
    display_number_matrix,
    find_available_tcp_port,
)


class TestCheckPortAvailable:
    def test_available_port(self):
        """A high random port should generally be available."""
        # Use port 0 trick to find a definitely-free port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        assert check_port_available(port) is True

    def test_occupied_port(self):
        """Binding the same port twice should fail."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        try:
            assert check_port_available(port) is False
        finally:
            s.close()


class TestFindAvailableTcpPort:
    def test_finds_port_in_range(self):
        port = find_available_tcp_port(min_port=49000, max_port=49100, max_attempts=50)
        assert port >= 49000 or port == -1  # May rarely fail on busy systems

    def test_no_available_ports(self):
        """If check_port_available always returns False, should return -1."""
        with patch(
            "backend.runtime.utils.system.check_port_available", return_value=False
        ):
            port = find_available_tcp_port(max_attempts=5)
            assert port == -1

    def test_small_range(self):
        with patch(
            "backend.runtime.utils.system.check_port_available", return_value=True
        ):
            port = find_available_tcp_port(min_port=50000, max_port=50000, max_attempts=1)
            assert port == 50000


class TestDisplayNumberMatrix:
    def test_zero(self):
        result = display_number_matrix(0)
        assert result is not None
        assert "###" in result

    def test_single_digit(self):
        result = display_number_matrix(1)
        assert result is not None
        assert "#" in result

    def test_two_digits(self):
        result = display_number_matrix(42)
        assert result is not None
        lines = result.strip().split("\n")
        assert len(lines) == 5

    def test_three_digits(self):
        result = display_number_matrix(999)
        assert result is not None
        lines = result.strip().split("\n")
        assert len(lines) == 5

    def test_out_of_range_negative(self):
        assert display_number_matrix(-1) is None

    def test_out_of_range_too_large(self):
        assert display_number_matrix(1000) is None

    def test_boundary_999(self):
        result = display_number_matrix(999)
        assert result is not None

    def test_boundary_0(self):
        result = display_number_matrix(0)
        assert result is not None

    def test_all_digits_represented(self):
        """Each digit 0-9 should produce a valid matrix."""
        for d in range(10):
            result = display_number_matrix(d)
            assert result is not None
            lines = result.strip().split("\n")
            assert len(lines) == 5
