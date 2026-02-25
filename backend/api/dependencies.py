"""FastAPI dependency helpers — auth disabled for local OSS use."""

from __future__ import annotations

from fastapi.params import Depends as DependsParam


def get_dependencies() -> list[DependsParam]:
    """Auth is disabled; returns an empty dependency list."""
    return []
