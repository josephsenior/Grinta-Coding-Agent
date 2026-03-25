"""Routes for collecting end-user feedback tied to conversations."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from backend.core.logger import forge_logger as logger
from backend.events.async_event_store_wrapper import AsyncEventStoreWrapper
from backend.events.event_filter import EventFilter
from backend.events.serialization import event_to_dict
from backend.api.schemas.feedback import FeedbackDataModel, store_feedback
from backend.api.route_dependencies import get_dependencies
from backend.api.session.conversation import ServerConversation
from backend.api.utils import get_conversation
from backend.utils.async_utils import call_sync_from_async

router = APIRouter(
    prefix="/api/v1/conversations/{conversation_id}/feedback",
    dependencies=get_dependencies(),
    tags=["feedback"],
)


@router.post("/submit-feedback")
async def submit_feedback(
    request: Request,
    conversation: ServerConversation = Depends(get_conversation),
) -> JSONResponse:
    r"""Submit user feedback with conversation trajectory.

    Captures user feedback about a conversation session, including email,
    system version, permission preferences, sentiment polarity, and the
    complete conversation trajectory for analysis.

    Args:
        request: HTTP request containing JSON body with:
            - email (str): User email address
            - version (str): Application version being used
            - permissions (str): Feedback sharing permission level (default: "private")
            - polarity (str): Sentiment polarity ("positive", "negative", "neutral")
            - feedback (str): Feedback text content
        conversation: Server conversation dependency containing the event stream
            for the current conversation session.

    Returns:
        JSONResponse: Status 200 with stored feedback data on success:
            {
                "email": str,
                "version": str,
                "permissions": str,
                "polarity": str,
                "feedback": str,
                "trajectory": list[dict],
                "created_at": str (ISO format)
            }

    Raises:
        HTTPException: 500 Internal Server Error if feedback storage fails
            or trajectory retrieval encounters an error.
        JSONDecodeError: If request body is not valid JSON.

    Examples:
        >>> curl -X POST http://localhost:3000/api/conversations/abc123/feedback/submit-feedback \\
        ...     -H "Content-Type: application/json" \\
        ...     -d '{"email": "user@example.com", "version": "1.0.0", "polarity": "positive"}'

    """
    body = await request.json()
    async_store = AsyncEventStoreWrapper(
        conversation.event_stream, filter=EventFilter(exclude_hidden=True)
    )
    trajectory = []
    async for event in async_store:
        trajectory.append(event_to_dict(event))
    feedback = FeedbackDataModel(
        session_id=conversation.sid,
        email=body.get("email", ""),
        version=body.get("version", ""),
        permissions=body.get("permissions", "private"),
        polarity=body.get("polarity", ""),
        feedback=body.get("feedback", ""),
        trajectory=trajectory,
    )
    try:
        feedback_data = await call_sync_from_async(store_feedback, feedback)
        return JSONResponse(status_code=status.HTTP_200_OK, content=feedback_data)
    except Exception as e:
        logger.error("Error submitting feedback: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Failed to submit feedback"},
        )

