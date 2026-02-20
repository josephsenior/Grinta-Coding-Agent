"""Shared FastAPI dependency helpers for route handlers.

Centralises the boilerplate that was duplicated across conversation.py and
manage_conversations.py (e.g. _require_conversation_manager,
_require_event_service_adapter).  Route files should import from here
instead of re-implementing these functions.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from backend.api.shared import (
    get_conversation_manager,
    get_event_service_adapter,
)


def get_conversation_manager_instance() -> Any | None:
    """Return the conversation manager singleton, or ``None`` on failure."""
    try:
        return get_conversation_manager()
    except Exception:
        return None


def require_conversation_manager() -> Any:
    """Return the conversation manager or raise HTTP 503."""
    manager = get_conversation_manager_instance()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation manager is not initialized",
        )
    return manager


def get_event_service_adapter_instance() -> Any | None:
    """Return the event service adapter singleton, or ``None`` on failure."""
    try:
        return get_event_service_adapter()
    except Exception:
        return None


def require_event_service_adapter() -> Any:
    """Return the event service adapter or raise HTTP 503."""
    adapter = get_event_service_adapter_instance()
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event service adapter is not initialized",
        )
    return adapter
