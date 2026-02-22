"""FastAPI dependency helpers — auth disabled for local OSS use."""

from __future__ import annotations

from fastapi.params import Depends as DependsParam


def check_session_api_key() -> None:
    """No-op: auth is disabled."""
    return


def get_dependencies() -> list[DependsParam]:
    """Auth is disabled; returns an empty dependency list."""
    return []
