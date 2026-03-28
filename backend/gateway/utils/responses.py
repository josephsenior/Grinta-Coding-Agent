"""Standardized API response helpers.

Provides a minimal, centralized set of helpers for success and error responses
so routes produce consistent JSON envelopes. These do NOT replace the rich
user-facing error formatting (see error_formatter) but wrap it in a stable
structure that clients can rely on.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

SUCCESS_STATUS = "ok"
ERROR_STATUS = "error"


def success(
    data: Any | None = None,
    *,
    message: str | None = None,
    status_code: int = 200,
    request: Request | None = None,
    **meta: Any,
) -> JSONResponse:
    """Return a standardized success response.

    Args:
        data: Primary payload (optional)
        message: Optional human-readable note
        status_code: HTTP status code (default 200)
        request: Optional request object for request ID
        **meta: Additional metadata merged under 'meta'
    """
    payload: dict[str, Any] = {
        "status": SUCCESS_STATUS,
        "timestamp": time.time(),
    }

    # Add request ID if available
    if request:
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            payload["request_id"] = request_id

    if message:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    if meta:
        payload["meta"] = meta
    return JSONResponse(status_code=status_code, content=payload)


def error(
    *,
    message: str,
    status_code: int = 400,
    error_code: str | None = None,
    details: Any | None = None,
    actions: Iterable[dict[str, Any]] | None = None,
    request: Request | None = None,
    **meta: Any,
) -> JSONResponse:
    """Return a standardized error response.

    This is a lightweight envelope. For rich user-facing errors produced by
    error_formatter, pass its dict as 'details' or merge fields here.

    Args:
        message: Error message
        status_code: HTTP status code (default 400)
        error_code: Machine-readable error code
        details: Additional error details
        actions: Suggested actions for the user
        request: Optional request object for request ID
        **meta: Additional metadata
    """
    payload: dict[str, Any] = {
        "status": ERROR_STATUS,
        "message": message,
        "timestamp": time.time(),
    }

    # Add request ID if available
    if request:
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            payload["request_id"] = request_id

    if error_code:
        payload["error_code"] = error_code
    if details is not None:
        payload["details"] = details
    if actions:
        payload["actions"] = list(actions)
    if meta:
        payload["meta"] = meta
    return JSONResponse(status_code=status_code, content=payload)


__all__ = ["success", "error", "SUCCESS_STATUS", "ERROR_STATUS"]
