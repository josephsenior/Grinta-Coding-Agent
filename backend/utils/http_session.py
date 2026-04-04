"""Wrapper around httpx.Client to guard against reuse after closing."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.core.logger import app_logger as logger

CLIENT = httpx.Client()


class SessionClosedError(RuntimeError):
    """Raised when a closed :class:`HttpSession` is used for a new request."""


@dataclass
class HttpSession:
    """Guard wrapper around :data:`CLIENT` that prevents reuse after :meth:`close`.

    Unlike the previous implementation, calling :meth:`request` / :meth:`stream`
    after :meth:`close` raises :class:`SessionClosedError` instead of silently
    resetting the closed flag (which would re-open the session and leak FDs).
    """

    _is_closed: bool = False
    headers: MutableMapping[str, str] = field(default_factory=dict)

    def _assert_open(self) -> None:
        """Raise if the session has already been closed."""
        if self._is_closed:
            logger.error(
                'HttpSession used after close — raising SessionClosedError.',
                stack_info=True,
            )
            raise SessionClosedError(
                'This HttpSession has been closed. Create a new instance.'
            )

    def _merged_headers(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        headers = kwargs.get('headers') or {}
        kwargs['headers'] = {**self.headers, **headers}
        return kwargs

    def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Proxy generic request while merging default headers and guarding reuse."""
        self._assert_open()
        kwargs = self._merged_headers(kwargs)
        return CLIENT.request(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        """Stream response content with default headers and reuse guard."""
        self._assert_open()
        kwargs = self._merged_headers(kwargs)
        return CLIENT.stream(*args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Send GET request via wrapped client."""
        return self.request('GET', *args, **kwargs)

    def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Send POST request via wrapped client."""
        return self.request('POST', *args, **kwargs)

    def patch(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Send PATCH request via wrapped client."""
        return self.request('PATCH', *args, **kwargs)

    def put(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Send PUT request via wrapped client."""
        return self.request('PUT', *args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Send DELETE request via wrapped client."""
        return self.request('DELETE', *args, **kwargs)

    def options(self, *args: Any, **kwargs: Any) -> httpx.Response:
        """Send OPTIONS request via wrapped client."""
        return self.request('OPTIONS', *args, **kwargs)

    def close(self) -> None:
        """Mark session closed to detect unintended reuse."""
        self._is_closed = True


__all__ = ['HttpSession', 'SessionClosedError', 'CLIENT']
