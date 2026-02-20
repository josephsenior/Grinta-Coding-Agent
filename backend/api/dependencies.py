"""FastAPI dependency helpers for validating session API keys.

These dependencies are used by route modules to make authentication appear
in OpenAPI, and must match the actual middleware enforcement.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.params import Depends as DependsParam
from fastapi.security import APIKeyHeader
from fastapi.security.utils import get_authorization_scheme_param

_SESSION_API_KEY_HEADER = APIKeyHeader(name="X-Session-API-Key", auto_error=False)


def check_session_api_key(
    request: Request,
    session_api_key: str | None = Depends(_SESSION_API_KEY_HEADER),
) -> None:
    """Check the session API key and throw an exception if incorrect.

    Having this as a dependency means it appears in OpenAPI Docs.
    """
    # 0) Bypass if local runtime
    import os

    if (
        os.environ.get("FORGE_RUNTIME") == "local"
        or os.environ.get("SESSION_API_KEY") == ""
    ):
        return

    # Resolve expected key from the live server config (not an import-time env snapshot)
    from backend.api.middleware.token_auth import get_session_api_key

    expected_key = get_session_api_key()
    if not expected_key:
        # Session API Key is explicitly disabled (empty string)
        return

    # 1) Header (preferred)
    if _check_header_auth(session_api_key, expected_key):
        return

    # 2) Authorization: Bearer <token>
    if _check_bearer_auth(request, expected_key):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing X-Session-API-Key",
    )


def get_dependencies() -> list[DependsParam]:
    """Get list of FastAPI dependencies for request validation.

    Returns API key check dependency if session API key is configured.

    Returns:
        List of Depends objects for dependency injection

    """
    # NOTE: ServerConfig auto-generates a session key by default, so auth is
    # typically always enabled. We still keep this dynamic check for flexibility.
    from backend.api.middleware.token_auth import get_session_api_key

    result: list[DependsParam] = []
    if get_session_api_key():
        result.append(Depends(check_session_api_key))
    return result


def _check_header_auth(session_api_key: str | None, expected_key: str) -> bool:
    """Check authentication via X-Session-API-Key header."""
    return bool(
        session_api_key and secrets.compare_digest(session_api_key, expected_key)
    )


def _check_bearer_auth(request: Request | None, expected_key: str) -> bool:
    """Check authentication via Authorization: Bearer <token>."""
    if request is None:
        return False

    authorization = request.headers.get("Authorization")
    scheme, bearer_token = get_authorization_scheme_param(authorization)
    if scheme.lower() == "bearer" and bearer_token:
        return secrets.compare_digest(bearer_token, expected_key)
    return False
