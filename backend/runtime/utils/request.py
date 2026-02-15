"""HTTP request helpers with retry logic for runtime components."""

import json
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backend.utils.http_session import HttpSession
from backend.utils.tenacity_metrics import (
    tenacity_after_factory,
    tenacity_before_sleep_factory,
)
from backend.utils.tenacity_stop import stop_if_should_exit


class RequestHTTPError(httpx.HTTPStatusError):
    """Exception raised when an error occurs in a request with details."""

    def __init__(self, *args: Any, detail: Any | None = None, **kwargs: Any) -> None:
        """Store optional error detail payload alongside standard HTTP status error data."""
        super().__init__(*args, **kwargs)
        self.detail = detail

    def __str__(self) -> str:
        """Render the base error string and append any captured detail metadata."""
        s = super().__str__()
        if self.detail is not None:
            s += f"\nDetails: {self.detail}"
        return str(s)


def is_retryable_error(exception: Any) -> bool:
    """Check if an exception is retryable (HTTP 429 status code).

    Args:
        exception: The exception to check.

    Returns:
        bool: True if the exception is retryable, False otherwise.

    """
    return (
        isinstance(exception, httpx.HTTPStatusError)
        and exception.response.status_code == 429
    )


@retry(
    retry=retry_if_exception(is_retryable_error),
    stop=stop_after_attempt(3) | stop_if_should_exit(),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=tenacity_before_sleep_factory("runtime.request.send_request"),
    after=tenacity_after_factory("runtime.request.send_request"),
)
def send_request(
    session: HttpSession, method: str, url: str, timeout: int = 60, **kwargs: Any
) -> httpx.Response:
    """Send an HTTP request with retry logic for rate limiting.

    Args:
        session: The HTTP session to use for the request.
        method: HTTP method (GET, POST, etc.).
        url: The URL to send the request to.
        timeout: Request timeout in seconds.
        **kwargs: Additional arguments to pass to the request.

    Returns:
        httpx.Response: The HTTP response.

    Raises:
        RequestHTTPError: If the request fails with HTTP error.

    """
    response = session.request(method, url, timeout=timeout, **kwargs)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail_payload: Any | None = None
        try:
            parsed = response.json()
        except json.decoder.JSONDecodeError:
            parsed = None
        finally:
            response.close()
        if isinstance(parsed, dict):
            detail_payload = parsed.get("detail")
        raise RequestHTTPError(
            *e.args,
            request=e.request,
            response=e.response,
            detail=detail_payload,
        ) from e
    except httpx.HTTPError:
        response.close()
        raise
    return response
