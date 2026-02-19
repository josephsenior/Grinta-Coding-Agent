"""Middleware to log request and response sizes without consuming bodies.

Logs request and response Content-Length values on the ACCESS logger.
Only uses headers to avoid interfering with streaming bodies.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request, Response

from backend.core.logger import access_logger


class RequestSizeLoggingMiddleware:
    """ASGI middleware that logs request/response sizes via ACCESS logger.

    It relies on the `Content-Length` headers when available. This avoids
    buffering request/response bodies and keeps overhead minimal.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        req_size = self._content_length_from_headers(request.headers)

        response = await call_next(request)

        resp_size = self._response_size(response)

        request_id = getattr(getattr(request, "state", object()), "request_id", None)
        if self._wrap_streaming_response(response, request, req_size, request_id):
            return response

        self._log_request_size(request, req_size, resp_size, request_id)
        return response

    def _content_length_from_headers(self, headers) -> int | None:
        try:
            if "content-length" in headers:
                return int(headers.get("content-length", "0"))
        except Exception:
            return None
        return None

    def _response_size(self, response: Response) -> int | None:
        try:
            if "content-length" in response.headers:
                return int(response.headers.get("content-length", "0"))
            body = getattr(response, "body", None)
            if isinstance(body, bytes | bytearray):
                return len(body)
        except Exception:
            return None
        return None

    def _wrap_streaming_response(
        self,
        response: Response,
        request: Request,
        req_size: int | None,
        request_id: str | None,
    ) -> bool:
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None or not callable(
            getattr(body_iterator, "__aiter__", None)
        ):
            return False

        if self._response_size(response) is not None:
            return False

        body_iter = body_iterator

        async def counting_aiter(aiter):
            total = 0
            async for chunk in aiter:
                if isinstance(chunk, bytes | bytearray):
                    total += len(chunk)
                yield chunk
            self._log_request_size(
                request,
                req_size,
                total,
                request_id,
                streaming=True,
            )

        try:
            setattr(response, "body_iterator", counting_aiter(body_iter))
            return True
        except Exception:
            return False

    def _log_request_size(
        self,
        request: Request,
        req_size: int | None,
        resp_size: int | None,
        request_id: str | None,
        streaming: bool = False,
    ) -> None:
        access_logger.info(
            "Request sizes",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "request_content_length": req_size,
                "response_content_length": resp_size,
                "streaming": streaming,
            },
        )
