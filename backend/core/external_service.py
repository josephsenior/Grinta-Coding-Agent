"""Base class for external services that send data over HTTP."""

from __future__ import annotations

from typing import Any
from collections.abc import Callable, Coroutine
from urllib.parse import ParseResult, urlparse

import aiohttp

from backend.core.logger import forge_logger as logger


class ExternalServiceBase:
    """Base class for external services with common HTTP logic."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        enabled: bool = False,
    ) -> None:
        """Initialize external service.

        Args:
            endpoint: External service endpoint URL.
            api_key: API key for the service.
            enabled: Whether the service is enabled.
        """
        self.endpoint = endpoint
        self.api_key = api_key
        self.enabled = enabled
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10.0)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _is_ready(self) -> bool:
        """Check if service is enabled and has an endpoint."""
        return bool(self.enabled and self.endpoint)

    def _get_parsed_endpoint(self) -> ParseResult:
        """Parse the endpoint URL.

        Returns:
            Parsed URL result.
        """
        return urlparse(self.endpoint or "")

    def _get_auth_headers(self, parsed_endpoint: ParseResult) -> dict[str, str]:
        """Build authentication headers based on the endpoint host.

        Args:
            parsed_endpoint: Parsed endpoint URL.

        Returns:
            Dictionary of headers.
        """
        headers = {"Content-Type": "application/json"}
        if not self.api_key:
            return headers

        host = parsed_endpoint.netloc.lower()
        if "pagerduty" in host:
            headers["Authorization"] = f"Token token={self.api_key}"
        elif "datadog" in host:
            headers["DD-API-KEY"] = self.api_key
        elif "logzio" in host:
            headers["X-API-KEY"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _prepare_request(
        self,
    ) -> tuple[aiohttp.ClientSession, ParseResult, dict[str, str]] | None:
        """Prepare session, parsed endpoint, and headers for a request.

        Returns:
            Tuple of (session, parsed_endpoint, headers) or None if not ready.
        """
        if not self._is_ready():
            return None

        session = await self._get_session()
        parsed_endpoint = self._get_parsed_endpoint()
        headers = self._get_auth_headers(parsed_endpoint)
        return session, parsed_endpoint, headers

    async def _send_request(
        self,
        build_payload: Callable[[ParseResult], Any],
        execute_request: Callable[
            [aiohttp.ClientSession, Any, dict[str, str]], Coroutine[Any, Any, bool]
        ],
        error_msg: str = "Error in external service request",
    ) -> bool:
        """Common request execution pattern with preparation and error handling.

        Args:
            build_payload: Function that takes parsed endpoint and returns payload.
            execute_request: Coroutine that takes session, payload, and headers and returns success.
            error_msg: Error message prefix for logging.

        Returns:
            True if successful, False otherwise.
        """
        prepared = await self._prepare_request()
        if not prepared:
            return False

        try:
            session, parsed_endpoint, headers = prepared
            payload = build_payload(parsed_endpoint)
            return await execute_request(session, payload, headers)
        except Exception as e:
            logger.error("%s: %s", error_msg, e, exc_info=True)
            return False
