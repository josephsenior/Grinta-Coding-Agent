"""Session management primitives exported for convenience."""

from __future__ import annotations

from typing import Any

__all__ = ["Session"]


def __getattr__(name: str) -> Any:
    if name == "Session":
        from backend.api.session.session import Session

        return Session
    raise AttributeError(name)
