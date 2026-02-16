"""FastAPI routes for managing conversations, runtimes, and event streams."""

from __future__ import annotations

import os
import sys
import json
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.config.llm_config import LLMConfig
from backend.core.errors import SessionInvariantError
from backend.core.logger import FORGE_logger as logger
from backend.core.pydantic_compat import model_to_dict
from backend.events.event_filter import EventFilter
from backend.events.event_store import EventStore
from backend.events.serialization.event import event_to_dict
from backend.instruction.types import InputMetadata
from backend.server.dependencies import get_dependencies
from backend.server.services.completion_service import (
    CompletionRequest,
    CompletionResult,
    format_error_message,
)
from backend.server.services.completion_service import (
    get_code_completion as _run_completion,
)
from backend.server.services.raw_event_service import dispatch_raw_message_event
from backend.server.services.shared_dependencies import (
    require_conversation_manager,
)
from backend.server.shared import file_store
from backend.server.user_auth import get_user_id, get_user_settings_store
from backend.server.utils import (
    get_conversation,
    get_conversation_metadata,
    get_conversation_store,
)
from backend.server.utils.responses import error

if TYPE_CHECKING:
    from backend.memory.agent_memory import Memory
    from backend.runtime.base import Runtime
    from backend.server.session.conversation import ServerConversation
    from backend.storage.data_models.conversation_metadata import ConversationMetadata


sub_router: APIRouter
if "pytest" in sys.modules:

    class NoOpAPIRouter(APIRouter):
        """Router stub used in tests to bypass actual FastAPI route wiring."""

        def add_api_route(self, path: str, endpoint, **kwargs):  # type: ignore[override]
            """Return endpoint unchanged so tests can call handler directly."""
            return endpoint

    sub_router = cast(APIRouter, NoOpAPIRouter())
else:
    sub_router = APIRouter(
        prefix="/api/v1/conversations/{conversation_id}",
        dependencies=get_dependencies(),
    )


def _get_workspace_dir(conversation_id: str) -> str:
    """Build the workspace directory for a conversation."""
    return os.path.join(os.path.expanduser(file_store.root), conversation_id)


@sub_router.get("/simple-test")
async def simple_test_endpoint() -> JSONResponse:
    """Simple test endpoint without any parameters."""
    return JSONResponse(content={"status": "simple_test_working"})


@sub_router.get("/config")
async def get_runtime_config(
    request: Request,
    conversation_id: str,  # Extracted from path by FastAPI
) -> JSONResponse:
    """Retrieve the runtime configuration.

    Currently, this is the session ID and runtime ID (if available).
    """
    manager = require_conversation_manager()
    user_id = get_user_id(request)

    try:
        conversation = await manager.attach_to_conversation(
            conversation_id, user_id or "dev-user"
        )
        if conversation:
            runtime = conversation.runtime
            runtime_id = runtime.runtime_id if hasattr(runtime, "runtime_id") else None
            session_id = runtime.sid if hasattr(runtime, "sid") else None
            await manager.detach_from_conversation(conversation)
            return JSONResponse(
                content={"runtime_id": runtime_id, "session_id": session_id}
            )
        return error(
            message="Conversation not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CONVERSATION_NOT_FOUND",
            request=request,
        )
    except Exception as e:
        logger.error("Error getting runtime config: %s", e, exc_info=True)
        return error(
            message=f"Error retrieving runtime configuration: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="RUNTIME_CONFIG_ERROR",
            request=request,
        )


@sub_router.get("/web-hosts")
async def get_hosts(
    request: Request,
    conversation_id: str,  # Extracted from path by FastAPI
) -> JSONResponse:
    """Get the hosts used by the runtime.

    This endpoint allows getting the hosts used by the runtime.

    Args:
        request: The FastAPI request object.
        conversation_id: The conversation ID.

    Returns:
        JSONResponse: A JSON response indicating the success of the operation.

    """
    manager = require_conversation_manager()
    user_id = get_user_id(request)

    try:
        conversation = await manager.attach_to_conversation(
            conversation_id, user_id or "dev-user"
        )
        if conversation:
            runtime: Runtime = conversation.runtime
            web_hosts = getattr(runtime, "web_hosts", None) or []
            logger.debug("Runtime type: %s", type(runtime))
            logger.debug("Runtime hosts: %s", web_hosts)
            await manager.detach_from_conversation(conversation)
            return JSONResponse(status_code=200, content={"hosts": web_hosts})
        return error(
            message="Conversation not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CONVERSATION_NOT_FOUND",
            request=request,
        )
    except Exception as e:
        logger.error("Error getting runtime hosts: %s", e, exc_info=True)
        return error(
            message=f"Error retrieving web hosts: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="WEB_HOSTS_ERROR",
            request=request,
        )


@sub_router.get("/events")
async def search_events(
    conversation_id: str,
    start_id: int = 0,
    end_id: int | None = None,
    reverse: bool = False,
    filter_json: str | None = Query(
        None,
        alias="filter",
        description="Optional JSON-encoded EventFilter fields",
    ),
    limit: int = 20,
    metadata: ConversationMetadata = Depends(get_conversation_metadata),
    user_id: str | None = Depends(get_user_id),
):
    """Search through the event stream with filtering and pagination.

    Args:
        conversation_id: The conversation ID
        start_id: Starting ID in the event stream. Defaults to 0
        end_id: Ending ID in the event stream
        reverse: Whether to retrieve events in reverse order. Defaults to False.
        filter: Filter for events
        limit: Maximum number of events to return. Must be between 1 and 100. Defaults to 20
        metadata: Conversation metadata (injected by dependency)
        user_id: User ID (injected by dependency)

    Returns:
        dict: Dictionary containing:
            - events: List of matching events
            - has_more: Whether there are more matching events after this batch
    Raises:
        HTTPException: If conversation is not found or access is denied
        ValueError: If limit is less than 1 or greater than 100

    """
    if limit < 1 or limit > 100:
        raise SessionInvariantError("limit must be between 1 and 100")
    if start_id < 0:
        raise SessionInvariantError("start_id must be non-negative")
    if end_id is not None and end_id < start_id:
        raise SessionInvariantError("end_id must be >= start_id")
    event_filter: EventFilter | None = None
    if filter_json:
        try:
            filter_payload = json.loads(filter_json)
            if isinstance(filter_payload, dict):
                event_filter = EventFilter(
                    exclude_hidden=bool(filter_payload.get("exclude_hidden", False)),
                    query=filter_payload.get("query"),
                    source=filter_payload.get("source"),
                    start_date=filter_payload.get("start_date"),
                    end_date=filter_payload.get("end_date"),
                )
        except JSONDecodeError as exc:
            raise SessionInvariantError("filter must be valid JSON") from exc

    event_store = EventStore(
        sid=conversation_id, file_store=file_store, user_id=user_id
    )
    events = list(
        event_store.search_events(
            start_id=start_id,
            end_id=end_id,
            reverse=reverse,
            filter=event_filter,
            limit=limit + 1,
        ),
    )
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]
    events_json = [event_to_dict(event) for event in events]
    return {"events": events_json, "has_more": has_more}


@sub_router.post("/events")
async def add_event(
    request: Request, conversation: ServerConversation = Depends(get_conversation)
):
    """Add an event to a conversation.

    Args:
        request: The HTTP request containing event data.
        conversation: The conversation to add the event to.

    Returns:
        JSONResponse: Success response or error details.

    """
    try:
        data = await request.json()
    except JSONDecodeError as e:
        raw = (await request.body()).decode("utf-8", errors="replace")
        logger.error(
            "Failed to parse JSON body for add_event: %s; raw body: %s", e, raw
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid JSON", "raw_body": raw[:2000]},
        )
    manager = require_conversation_manager()
    await manager.send_event_to_conversation(conversation.sid, data)
    return JSONResponse({"success": True})


@sub_router.post("/events/raw")
async def add_event_raw(
    request: Request,
    conversation_id: str,
    create: bool | None = False,
    user_id: str | None = Depends(get_user_id),
    conversation_store: Any | None = Depends(get_conversation_store),
):
    """Accept raw text/plain POSTs and forward them as a MessageAction.

    This is a developer convenience so tools that have trouble building
    JSON bodies (PowerShell curl, etc.) can still send messages to the
    conversation. The raw body becomes the action args.content.
    """
    try:
        raw = (await request.body()).decode("utf-8", errors="replace")
        return await dispatch_raw_message_event(
            conversation_id=conversation_id,
            user_id=user_id,
            raw_body=raw,
            create_if_missing=bool(create),
            conversation_store=conversation_store,
        )
    except Exception as e:
        logger.exception("Failed to handle raw event body: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


class PlaybookResponse(BaseModel):
    """Response model for playbooks endpoint."""

    name: str
    type: str
    content: str
    triggers: list[str] = []
    inputs: list[InputMetadata] = []
    tools: list[str] = []


@sub_router.get("/playbooks")
async def get_playbooks(
    conversation: ServerConversation = Depends(get_conversation),
) -> JSONResponse:
    """Get all playbooks associated with the conversation.

    This endpoint returns all repository and knowledge playbooks that are loaded for the conversation.

    Args:
        conversation: Server conversation dependency

    Returns:
        JSON response containing the list of playbooks

    """
    try:
        memory = _get_conversation_memory(conversation)
        playbooks = _build_playbook_list(memory)

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"playbooks": [model_to_dict(m) for m in playbooks]},
        )
    except HTTPException as exc:
        detail_obj: Any = exc.detail
        if not isinstance(detail_obj, dict):
            detail_obj = {"error": str(detail_obj)}
        detail_data = cast(dict[str, Any], detail_obj)
        logger.warning(
            "Error getting playbooks: %s",
            detail_data.get("error", detail_data),
            exc_info=False,
        )
        return JSONResponse(status_code=exc.status_code, content=detail_data)
    except Exception as e:
        logger.error("Error getting playbooks: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": f"Error getting playbooks: {e}"},
        )


def _get_conversation_memory(conversation: ServerConversation) -> Memory:
    """Get memory from conversation session.

    Args:
        conversation: Server conversation

    Returns:
        Memory object

    Raises:
        HTTPException: If session or memory not found

    """
    manager = require_conversation_manager()
    agent_session = manager.get_agent_session(conversation.sid)
    if not agent_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent session not found for this conversation",
        )

    memory = agent_session.memory
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory is not yet initialized for this conversation",
        )

    return memory


def _build_playbook_list(memory: Memory) -> list[PlaybookResponse]:
    """Build list of playbook responses from memory.

    Args:
        memory: Conversation memory

    Returns:
        List of playbook response objects

    """
    # Build repo playbooks
    repo_playbooks = [
        _build_repo_playbook(name, r_agent)
        for name, r_agent in memory.repo_playbooks.items()
    ]

    # Build knowledge playbooks
    knowledge_playbooks = [
        _build_knowledge_playbook(name, k_agent)
        for name, k_agent in memory.knowledge_playbooks.items()
    ]

    return repo_playbooks + knowledge_playbooks


def _build_repo_playbook(name: str, r_agent) -> PlaybookResponse:
    """Build playbook response for repo playbook.

    Args:
        name: Playbook name
        r_agent: Repository agent object

    Returns:
        PlaybookResponse object

    """
    return PlaybookResponse(
        name=name,
        type="repo",
        content=r_agent.content,
        triggers=[],
        inputs=r_agent.metadata.inputs,
        tools=_extract_mcp_tools(r_agent),
    )


def _build_knowledge_playbook(name: str, k_agent) -> PlaybookResponse:
    """Build playbook response for knowledge playbook.

    Args:
        name: Playbook name
        k_agent: Knowledge agent object

    Returns:
        PlaybookResponse object

    """
    return PlaybookResponse(
        name=name,
        type="knowledge",
        content=k_agent.content,
        triggers=k_agent.triggers,
        inputs=k_agent.metadata.inputs,
        tools=_extract_mcp_tools(k_agent),
    )


def _extract_mcp_tools(agent) -> list[str]:
    """Extract MCP tool names from agent metadata.

    Args:
        agent: Agent object with metadata

    Returns:
        List of MCP tool server names

    """
    if agent.metadata.mcp_tools:
        return [server.name for server in agent.metadata.mcp_tools.stdio_servers]
    return []


class CodeCompletionRequest(BaseModel):
    """Request model for code completion."""

    filePath: str
    fileContent: str
    language: str
    position: dict[str, int]  # {line: int, character: int}
    prefix: str
    suffix: str


class CodeCompletionResponse(BaseModel):
    """Response model for code completion."""

    completion: str
    stopReason: str | None = None


@sub_router.post("/completions", response_model=CodeCompletionResponse)
async def get_code_completion(
    request: Request,
    request_body: CodeCompletionRequest,
    conversation: ServerConversation = Depends(get_conversation),
    user_id: str | None = Depends(get_user_id),
) -> JSONResponse:
    """Get code completion suggestions for the current position in a file.

    Delegates all resilience logic (circuit breaker, retry, budget, security,
    anti-hallucination) to ``CompletionService``.
    """
    from backend.core.cache.async_smart_cache import AsyncSmartCache
    from backend.engines.orchestrator.file_verification_guard import (
        FileVerificationGuard,
    )

    anti_hallucination = FileVerificationGuard()

    # Load LLM config from user settings
    cache = AsyncSmartCache()
    user_settings_store = get_user_settings_store(request)
    if not user_settings_store:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "User settings store not available."},
        )
    settings = await cache.get_user_settings(
        user_id or "anonymous", user_settings_store
    )
    if not settings or not settings.llm_model:
        settings = await user_settings_store.load()
        if not settings or not settings.llm_model:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": "LLM settings not configured. Please configure your LLM settings first."
                },
            )

    llm_config = LLMConfig(
        model=settings.llm_model or "",
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )

    manager = require_conversation_manager()

    try:
        result: CompletionResult = await _run_completion(
            req=CompletionRequest(
                file_path=request_body.filePath,
                file_content=request_body.fileContent,
                language=request_body.language,
                position=request_body.position,
                prefix=request_body.prefix,
                suffix=request_body.suffix,
            ),
            conversation_sid=conversation.sid,
            user_id=user_id,
            llm_config=llm_config,
            manager=manager,
            anti_hallucination=anti_hallucination,
        )
        content: dict[str, Any] = {
            "completion": result.completion,
            "stopReason": result.stop_reason,
        }
        if result.error:
            content["error"] = result.error
        if result.error_type:
            content["errorType"] = result.error_type
        if result.warning:
            content["warning"] = result.warning
        if result.security_risk:
            content["securityRisk"] = result.security_risk
        return JSONResponse(status_code=result.status_code, content=content)
    except HTTPException:
        raise
    except Exception as e:
        error_type = ErrorRecoveryStrategy.classify_error(e)
        logger.error("Completion error (%s): %s", error_type.value, e, exc_info=True)
        status_map = {
            ErrorType.NETWORK_ERROR: status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorType.TIMEOUT_ERROR: status.HTTP_504_GATEWAY_TIMEOUT,
            ErrorType.PERMISSION_ERROR: status.HTTP_403_FORBIDDEN,
        }
        return JSONResponse(
            status_code=status_map.get(
                error_type, status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            content={
                "error": format_error_message(e, error_type),
                "errorType": error_type.value,
                "completion": "",
                "stopReason": "error",
            },
        )
