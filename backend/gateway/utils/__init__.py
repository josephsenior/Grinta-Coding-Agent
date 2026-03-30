"""Server utility package exports."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status

from backend.core.logger import app_logger as logger
from backend.gateway.app_accessors import ConversationStoreImpl, config
from backend.gateway.store_factory import get_conversation_store_instance
from backend.gateway.user_auth import get_user_id
from backend.persistence.conversation.conversation_store import ConversationStore
from backend.persistence.data_models.conversation_metadata import ConversationMetadata

from .error_formatter import safe_format_error  # noqa: F401

if TYPE_CHECKING:
    pass


def validate_conversation_id(conversation_id: str) -> str:
    """Validate conversation ID format and length.

    Args:
        conversation_id: The conversation ID to validate

    Returns:
        The validated conversation ID

    Raises:
        HTTPException: If the conversation ID is invalid

    """
    from backend.core.type_safety.type_safety import validate_non_empty_string

    # First check: non-empty string
    conversation_id = validate_non_empty_string(conversation_id, name="conversation_id")

    # Then check length and format
    if len(conversation_id) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation ID is too long",
        )
    if "\x00" in conversation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation ID contains invalid characters",
        )
    if ".." in conversation_id or "/" in conversation_id or "\\" in conversation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation ID contains invalid path characters",
        )
    if any(ord(c) < 32 for c in conversation_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conversation ID contains control characters",
        )
    return conversation_id


async def resolve_conversation_store(
    request: Request | None = None,
) -> ConversationStore | None:
    """Resolve a conversation store instance for the given request.

    Caches instance in request state for reuse when a request is provided.

    Args:
        request: HTTP request, if available

    Returns:
        ConversationStore instance or None

    """
    if request is None:
        return await get_conversation_store_instance(
            ConversationStoreImpl, config, None
        )

    conversation_store: ConversationStore | None = getattr(
        request.state, "conversation_store", None
    )
    if conversation_store:
        return conversation_store
    user_id = get_user_id(request)
    conversation_store = await get_conversation_store_instance(
        ConversationStoreImpl, config, user_id
    )
    request.state.conversation_store = conversation_store
    return conversation_store


async def get_conversation_store(request: Request) -> ConversationStore | None:
    """FastAPI dependency that returns the conversation store for the active request."""
    return await resolve_conversation_store(request)


async def generate_unique_conversation_id(conversation_store: ConversationStore) -> str:
    """Generate a unique conversation ID that doesn't exist in store.

    Repeatedly generates UUIDs until finding one not already in use.

    Args:
        conversation_store: Conversation storage

    Returns:
        Unique conversation ID as hex string

    """
    conversation_id = uuid.uuid4().hex
    while await conversation_store.exists(conversation_id):
        conversation_id = uuid.uuid4().hex
    return conversation_id


async def get_conversation_metadata(
    conversation_id: str,
    conversation_store: ConversationStore = Depends(get_conversation_store),
) -> ConversationMetadata:
    """Get conversation metadata and validate user access without requiring an active conversation."""
    try:
        return await conversation_store.get_metadata(conversation_id)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        ) from e


async def get_conversation(
    conversation_id: str, user_id: str | None = Depends(get_user_id)
):
    """Grabs conversation id set by middleware. Adds the conversation_id to the openapi schema."""
    # For testing, default to "dev-user" if no user_id
    user_id = user_id or "dev-user"
    logger.info(
        "get_conversation called with conversation_id=%s, user_id=%s",
        conversation_id,
        user_id,
    )

    # First check if conversation exists in conversation store
    conversation_store = await get_conversation_store_instance(
        ConversationStoreImpl, config, user_id
    )
    conversation_metadata = await conversation_store.get_metadata(conversation_id)
    if not conversation_metadata:
        logger.warning(
            "get_conversation: conversation %s not found in conversation store",
            conversation_id,
            extra={"session_id": conversation_id, "user_id": user_id},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )

    # Get the ServerConversation from conversation manager.
    # Resolve the conversation manager lazily to avoid relying on a module-level
    # snapshot (some modules import the value at import-time and won't see
    # updates). Import locally to avoid circular import problems.
    from backend.gateway.app_accessors import get_conversation_manager

    try:
        # Always resolve via accessor to ensure we obtain the live singleton
        manager = get_conversation_manager()
    except Exception as exc:
        # If resolving the manager raises, log and surface as service unavailable.
        logger.exception("Error resolving conversation manager: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation manager is not initialized",
        ) from exc

    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation manager is not initialized",
        )

    conversation = await manager.attach_to_conversation(conversation_id, user_id)
    if not conversation:
        logger.warning(
            "get_conversation: conversation %s not found, attach_to_conversation returned None",
            conversation_id,
            extra={"session_id": conversation_id, "user_id": user_id},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found",
        )
    try:
        yield conversation
    finally:
        await manager.detach_from_conversation(conversation)
