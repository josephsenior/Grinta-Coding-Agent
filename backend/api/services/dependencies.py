"""FastAPI dependency helpers for route handlers.

Centralises the boilerplate that was duplicated across conversation.py and
manage_conversations.py (e.g. _require_conversation_manager,
_require_event_service_adapter).  Route files should import from here
instead of re-implementing these functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

from backend.api.app_state import get_app_state
from backend.api.app_accessors import (
    get_conversation_manager,
    get_event_service_adapter,
)

if TYPE_CHECKING:
    from backend.core.config import ForgeConfig
    from backend.api.config.server_config import ServerConfig
    from backend.storage.files import FileStore


def get_file_store() -> "FileStore":
    """FastAPI dependency that returns the shared FileStore singleton."""
    return get_app_state().file_store


def get_forge_config() -> "ForgeConfig":
    """FastAPI dependency that returns the current ForgeConfig.

    Reads directly from AppState on each call to avoid the stale-snapshot
    problem with the module-level ``config`` reference in ``app_accessors``.
    """
    return get_app_state().config


def get_server_config() -> "ServerConfig":
    """FastAPI dependency that returns the ServerConfig singleton."""
    return get_app_state().server_config


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
