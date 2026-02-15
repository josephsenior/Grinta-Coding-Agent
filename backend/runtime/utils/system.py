"""System utility helpers for port checks and simple diagnostics."""

from __future__ import annotations

import random
import socket
import time


def check_port_available(port: int) -> bool:
    """Check if a port is available for binding.

    Args:
        port: The port number to check.

    Returns:
        bool: True if the port is available, False otherwise.

    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Bind to loopback to avoid exposing the port check on all interfaces
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        time.sleep(0.1)
        return False
    finally:
        sock.close()


def find_available_tcp_port(
    min_port: int = 30000, max_port: int = 39999, max_attempts: int = 10
) -> int:
    """Find an available TCP port in a specified range.

    Args:
        min_port (int): The lower bound of the port range (default: 30000)
        max_port (int): The upper bound of the port range (default: 39999)
        max_attempts (int): Maximum number of attempts to find an available port (default: 10)

    Returns:
        int: An available port number, or -1 if none found after max_attempts

    """
    rng = random.SystemRandom()
    ports = list(range(min_port, max_port + 1))
    rng.shuffle(ports)
    return next(
        (port for port in ports[:max_attempts] if check_port_available(port)), -1
    )


def display_number_matrix(number: int) -> str | None:
    """Display a number as a matrix pattern using ASCII characters.

    Args:
        number: The number to display (0-999).

    Returns:
        str | None: The matrix pattern as a string, or None if number is out of range.

    """
    if not 0 <= number <= 999:
        return None
    digits = {
        "0": ["###", "# #", "# #", "# #", "###"],
        "1": ["  #", "  #", "  #", "  #", "  #"],
        "2": ["###", "  #", "###", "#  ", "###"],
        "3": ["###", "  #", "###", "  #", "###"],
        "4": ["# #", "# #", "###", "  #", "  #"],
        "5": ["###", "#  ", "###", "  #", "###"],
        "6": ["###", "#  ", "###", "# #", "###"],
        "7": ["###", "  #", "  #", "  #", "  #"],
        "8": ["###", "# #", "###", "# #", "###"],
        "9": ["###", "# #", "###", "  #", "###"],
    }
    num_str = str(number)
    result = [" ".join(digits[digit][row] for digit in num_str) for row in range(5)]
    matrix_display = "\n".join(result)
    return f"\n{matrix_display}\n"
