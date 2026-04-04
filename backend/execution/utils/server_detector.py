"""Server detection module for automatic app rendering.

This module provides production-grade server detection by combining:
1. Pattern detection from command output
2. Port monitoring to verify servers are listening
3. Health checks to confirm HTTP servers are responding

Used to automatically navigate the browser to apps when they start.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from dataclasses import dataclass
from typing import Any, Literal

import httpx

try:
    import aiohttp as _aiohttp  # type: ignore[import]
except Exception:  # pragma: no cover - optional dependency
    _aiohttp = None  # type: ignore[assignment]

aiohttp: Any | None = _aiohttp

logger = logging.getLogger(__name__)

# Port ranges for app servers (no longer used with in-process runtime)
APP_PORT_RANGE_1 = (50000, 54999)
APP_PORT_RANGE_2 = (55000, 59999)


@dataclass
class DetectedServer:
    """Information about a detected server."""

    port: int
    url: str
    protocol: str  # 'http' or 'https'
    health_status: str  # 'healthy', 'unhealthy', 'unknown'
    command_hint: str | None = None  # The command that started it


# Server start patterns - matches common dev server outputs
SERVER_START_PATTERNS = [
    # Generic patterns
    (
        r'(?:Server|App|Application|Development\s+server).*(?:listening|running|started).*(?:port|:)\s*(\d+)',
        'http',
    ),
    (
        r'(?:Local|Network):\s*https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)',
        'http',
    ),
    # Vite
    (r'Local:\s+https?://localhost:(\d+)', 'http'),
    (r'VITE.*ready.*:(\d+)', 'http'),
    # Webpack
    (r'webpack.*compiled.*https?://(?:localhost|127\.0\.0\.1):(\d+)', 'http'),
    (r'Project is running at\s+https?://(?:localhost|127\.0\.0\.1):(\d+)', 'http'),
    # Next.js
    (r'(?:ready|started)\s+server\s+on.*:(\d+)', 'http'),
    (r'Local:\s+https?://localhost:(\d+)', 'http'),
    # Create React App
    (r'(?:webpack\s+)?compiled successfully.*localhost:(\d+)', 'http'),
    (r'On Your Network:\s+https?://(?:[^:]+):(\d+)', 'http'),
    # Express/Node
    (r'(?:Express|Server|App).*listening.*port\s+(\d+)', 'http'),
    (r'Server running at\s+https?://(?:localhost|127\.0\.0\.1):(\d+)', 'http'),
    # Django
    (
        r'Starting development server at\s+https?://(?:localhost|127\.0\.0\.1):(\d+)',
        'http',
    ),
    # Flask
    (r'Running on\s+https?://(?:localhost|127\.0\.0\.1):(\d+)', 'http'),
    # Python http.server
    (r'Serving HTTP on.*port\s+(\d+)', 'http'),
    # Generic localhost URLs
    (r'https?://(localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)', 'http'),
]


def extract_port_from_output(output: str) -> tuple[int, str, str] | None:
    """Extract server port from command output using pattern matching.

    Args:
        output: Command output text to analyze

    Returns:
        Tuple of (port, protocol, matched_line) if found, None otherwise

    """
    lines = output.split('\n')

    # Check last 50 lines (servers usually announce in recent output)
    for line in lines[-50:]:
        for pattern, protocol in SERVER_START_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    # Extract port from the last capturing group
                    port_str = match.groups()[-1]
                    port = int(port_str)

                    # Validate port is in valid range (1024-65535, excluding system ports)
                    if 1024 <= port <= 65535:
                        logger.info(
                            "Detected server start: port=%d, line='%s'",
                            port,
                            line.strip(),
                        )
                        return (port, protocol, line.strip())
                except (ValueError, IndexError):
                    continue

    return None


def is_port_listening(port: int, host: str = 'localhost', timeout: float = 0.5) -> bool:
    """Check if a port is actively listening for connections.

    Args:
        port: Port number to check
        host: Host to check (default: localhost)
        timeout: Connection timeout in seconds

    Returns:
        True if port is listening, False otherwise

    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0  # 0 means connection successful
    except OSError:
        return False
    finally:
        sock.close()


def health_check_http(port: int, host: str = 'localhost', timeout: float = 2.0) -> str:
    """Perform HTTP health check on a port.

    Args:
        port: Port number to check
        host: Host to check
        timeout: HTTP request timeout

    Returns:
        'healthy' if responds with 2xx/3xx, 'unhealthy' if 4xx/5xx or no response

    """
    scheme_host = 'localhost' if host in ('localhost', '127.0.0.1') else host
    scheme = 'http' if scheme_host in ('localhost', '127.0.0.1') else 'https'
    url = f'{scheme}://{scheme_host}:{port}'
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
        # Accept 2xx, 3xx, and even 404 (single-page apps often show 404 for API routes)
        if response.status_code < 500:
            logger.info(
                'Health check passed: %s returned %d', url, response.status_code
            )
            return 'healthy'
        logger.warning('Health check failed: %s returned %d', url, response.status_code)
        return 'unhealthy'
    except httpx.HTTPError as e:
        logger.debug('Health check failed: %s - %s', url, type(e).__name__)
        return 'unhealthy'


async def health_check_http_async(
    port: int,
    host: str = 'localhost',
    request_timeout: float = 2.0,
) -> Literal['healthy', 'unhealthy']:
    """Async HTTP health check using aiohttp when available.

    Falls back to running the sync requests-based check in a thread if aiohttp is unavailable.

    Args:
        port: Port number to check
        host: Host to check
        request_timeout: HTTP request timeout

    Returns:
        'healthy' or 'unhealthy'

    """
    url = f'http://{host}:{port}'
    if aiohttp is None:
        # Run sync check in a thread to avoid blocking event loop
        sync_result = await asyncio.to_thread(
            health_check_http, port, host, request_timeout
        )
        return 'healthy' if sync_result == 'healthy' else 'unhealthy'
    timeout_cfg = aiohttp.ClientTimeout(total=request_timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.get(url, allow_redirects=False) as resp:
                status = resp.status
                if status < 500:
                    logger.info('Health check passed: %s returned %d', url, status)
                    return 'healthy'
                logger.warning('Health check failed: %s returned %d', url, status)
                return 'unhealthy'
    except Exception as e:  # Broad except to mirror sync function behavior
        logger.debug('Health check failed: %s - %s', url, type(e).__name__)
        return 'unhealthy'


def detect_server_from_output(
    output: str,
    perform_health_check: bool = True,
) -> DetectedServer | None:
    """Detect and validate a server from command output.

    This is the main entry point combining all detection layers:
    1. Pattern matching to extract port
    2. Socket check to verify port is listening
    3. HTTP health check to confirm server is responding

    Args:
        output: Command output to analyze
        perform_health_check: Whether to perform HTTP health check (default: True)

    Returns:
        DetectedServer if found and validated, None otherwise

    """
    # Layer 1: Pattern detection
    result = extract_port_from_output(output)
    if not result:
        return None

    port, protocol, command_hint = result

    # Layer 2: Port monitoring
    if not is_port_listening(port):
        logger.debug('Port %d detected in output but not listening yet', port)
        return None

    logger.info('Port %d is listening, server detected!', port)

    # Layer 3: Health check (optional for performance)
    health_status = 'unknown'
    if perform_health_check:
        health_status = health_check_http(port)
        if health_status == 'unhealthy':
            logger.warning('Port %d is listening but health check failed', port)
            # Still return it - some servers take time to fully initialize

    url = f'{protocol}://localhost:{port}'

    return DetectedServer(
        port=port,
        url=url,
        protocol=protocol,
        health_status=health_status,
        command_hint=command_hint,
    )
