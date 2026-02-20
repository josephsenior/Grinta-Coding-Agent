"""Routes for exporting or inspecting conversation event trajectories."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse

from backend.core.logger import forge_logger as logger
from backend.api.dependencies import get_dependencies
from backend.api.services.trajectory_service import export_trajectory
from backend.api.session.conversation import ServerConversation
from backend.api.session.session_contract import normalize_replay_cursor
from backend.api.utils import get_conversation

router = APIRouter(
    prefix="/api/v1/conversations/{conversation_id}/trajectory",
    dependencies=get_dependencies(),
)


@router.get("/")
async def get_trajectory(
    conversation_id: Annotated[
        str, Path(..., min_length=1, description="Conversation ID")
    ],
    since_id: Annotated[
        int | None,
        Query(description="Return events with id > since_id (for reconnect)"),
    ] = None,
    limit: Annotated[
        int | None, Query(ge=1, le=5000, description="Max events to return")
    ] = None,
    conversation: ServerConversation = Depends(get_conversation),
) -> JSONResponse:
    """Get trajectory history for a conversation.

    Supports optional pagination via ``since_id`` (for reconnection-based
    delta fetches) and ``limit`` (cap returned events).

    Events are read from the conversation's file-backed event stream.
    """
    # Safety guardrail: default limit applies when the caller doesn't request paging.
    cursor = normalize_replay_cursor(since_id=since_id, limit=limit)

    logger.info(
        "Returning trajectory for %s (start_id=%s, limit=%s)",
        conversation_id,
        cursor.start_id,
        cursor.limit,
    )

    trajectory = export_trajectory(conversation=conversation, cursor=cursor)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"trajectory": trajectory},
    )
