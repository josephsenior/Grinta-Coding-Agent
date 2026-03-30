"""Session management primitives exported for convenience."""

from __future__ import annotations

from typing import Any

__all__ = ["Session", "Run"]


def __getattr__(name: str) -> Any:
    if name in {"Session", "Run"}:
        from backend.gateway.session.session import Session

        return Session
    raise AttributeError(name)
