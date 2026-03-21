"""Service helpers for raw event ingestion endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from backend.core.logger import forge_logger as logger
from backend.events.event import EventSource
from backend.events.serialization.event import event_from_dict
from backend.api.services.dependencies import (
    require_conversation_manager,
    require_event_service_adapter,
)
from backend.storage.data_models.conversation_metadata import ConversationMetadata


async def dispatch_raw_message_event(
    *,
    conversation_id: str,
    user_id: str | None,
    raw_body: str,
    create_if_missing: bool,
    conversation_store: Any | None,
) -> JSONResponse:
    """Dispatch a text payload as ``MessageAction`` to a conversation."""
    if not raw_body:
        return JSONResponse(status_code=400, content={"error": "Empty body"})

    manager = require_conversation_manager()
    adapter = require_event_service_adapter()

    conversation = await manager.attach_to_conversation(conversation_id, user_id)
    if not conversation and create_if_missing:
        if conversation_store is None:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Conversation store unavailable"},
            )
        metadata = ConversationMetadata(
            conversation_id=conversation_id,
            selected_repository=None,
            title=f"Conversation {conversation_id}",
        )
        await conversation_store.save_metadata(metadata)
        conversation = await manager.attach_to_conversation(conversation_id, user_id)

    if not conversation:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": f"no_conversation:{conversation_id}",
                "hint": "Create a conversation first (POST /api/conversations) or call this endpoint with ?create=true to create a minimal conversation metadata before sending raw events.",
            },
        )

    data = {"action": "message", "args": {"content": raw_body}}
    try:
        await manager.send_event_to_conversation(conversation.sid, data)
        return JSONResponse({"success": True, "dispatched_as": data})
    except RuntimeError as err:
        if not str(err).startswith("no_conversation:"):
            raise

        event_obj = event_from_dict(data.copy())
        adapter.start_session(
            session_id=conversation_id,
            user_id=user_id,
            labels={"source": "conversation_route"},
        )
        event_stream = adapter.get_event_stream(conversation_id)
        event_stream.add_event(event_obj, EventSource.USER)
        logger.info(
            "Raw event persisted directly to event stream for %s", conversation_id
        )
        return JSONResponse(
            {
                "success": True,
                "dispatched_as": data,
                "note": "persisted_to_event_store",
            }
        )
