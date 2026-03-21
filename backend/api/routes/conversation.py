"""FastAPI routes for managing conversations, runtimes, and event streams."""

from __future__ import annotations

import os
import re
import json
import shutil
from json import JSONDecodeError
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.config.llm_config import LLMConfig
from backend.core.errors import SessionInvariantError
from backend.core.logger import forge_logger as logger
from backend.core.pydantic_compat import model_to_dict
from backend.events.action.files import FileWriteAction
from backend.events.event_filter import EventFilter
from backend.events.event_store import EventStore
from backend.events.serialization.event import event_to_dict
from backend.playbook_engine.playbook import BasePlaybook
from backend.playbook_engine.types import InputMetadata
from backend.api.dependencies import get_dependencies
from backend.api.services.completion_service import (
    CompletionRequest,
    CompletionResult,
    format_error_message,
)
from backend.api.services.completion_service import (
    get_code_completion as _run_completion,
)
from backend.api.services.raw_event_service import dispatch_raw_message_event
from backend.api.services.dependencies import (
    require_conversation_manager,
)
from backend.api.app_state import get_app_state
from backend.api.user_auth import get_user_id, get_user_settings_store
from backend.api.utils import (
    get_conversation,
    get_conversation_store,
)
from backend.api.utils.responses import error
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.memory.agent_memory import Memory
    from backend.runtime.base import Runtime
    from backend.api.session.conversation import ServerConversation


sub_router = APIRouter(
    prefix="/api/v1/conversations/{conversation_id}",
    dependencies=get_dependencies(),
    tags=["conversations"],
)


def _get_workspace_dir(conversation_id: str) -> str:
    """Build the workspace directory for a conversation."""
    return os.path.join(os.path.expanduser(get_app_state().file_store.root), conversation_id)


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


def _validate_search_events_params(
    limit: int, start_id: int, end_id: int | None
) -> None:
    """Validate search_events parameters. Raises SessionInvariantError on failure."""
    if limit < 1 or limit > 100:
        raise SessionInvariantError("limit must be between 1 and 100")
    if start_id < 0:
        raise SessionInvariantError("start_id must be non-negative")
    if end_id is not None and end_id < start_id:
        raise SessionInvariantError("end_id must be >= start_id")


def _parse_event_filter(filter_json: str | None) -> EventFilter | None:
    """Parse JSON filter string into EventFilter. Raises SessionInvariantError on bad JSON."""
    if not filter_json:
        return None
    try:
        filter_payload = json.loads(filter_json)
        if not isinstance(filter_payload, dict):
            return None
        return EventFilter(
            exclude_hidden=bool(filter_payload.get("exclude_hidden", False)),
            query=filter_payload.get("query"),
            source=filter_payload.get("source"),
            start_date=filter_payload.get("start_date"),
            end_date=filter_payload.get("end_date"),
        )
    except JSONDecodeError as exc:
        raise SessionInvariantError("filter must be valid JSON") from exc


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
        user_id: User ID (injected by dependency)

    Returns:
        dict: Dictionary containing:
            - events: List of matching events
            - has_more: Whether there are more matching events after this batch
    Raises:
        HTTPException: If conversation is not found or access is denied
        ValueError: If limit is less than 1 or greater than 100

    """
    _validate_search_events_params(limit, start_id, end_id)
    event_filter = _parse_event_filter(filter_json)

    events = await call_sync_from_async(
        _search_events_sync,
        conversation_id,
        user_id,
        start_id,
        end_id,
        reverse,
        event_filter,
        limit + 1,
    )

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]
    events_json = [event_to_dict(event) for event in events]
    return {"events": events_json, "has_more": has_more}


def _search_events_sync(
    conversation_id: str,
    user_id: str | None,
    start_id: int,
    end_id: int | None,
    reverse: bool,
    event_filter: EventFilter | None,
    limit: int,
) -> list:
    """Run EventStore.search_events synchronously for threadpool execution."""
    event_store = EventStore(
        sid=conversation_id,
        file_store=get_app_state().file_store,
        user_id=user_id,
    )
    return list(
        event_store.search_events(
            start_id=start_id,
            end_id=end_id,
            reverse=reverse,
            filter=event_filter,
            limit=limit,
        )
    )


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
    source: str = ""
    description: str = ""
    triggers: list[str] = []
    inputs: list[InputMetadata] = []
    tools: list[str] = []


class UpdatePlaybookRequest(BaseModel):
    """Body for updating playbook markdown on disk (workspace playbooks only)."""

    content: str
    name: str | None = Field(
        default=None,
        description="If set, renames the playbook (only under .Forge/playbooks).",
    )


def _validate_playbook_name_key(raw: str) -> str:
    """Return normalized playbook key (no .md); raises HTTPException if invalid."""
    s = raw.strip().strip("/")
    if not s or ".." in s:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid playbook name",
        )
    parts = PurePosixPath(s).parts
    for p in parts:
        if not p or p in (".", ".."):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid playbook name",
            )
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", p):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Playbook name segments may only contain letters, digits, hyphen, and underscore",
            )
    return "/".join(parts)


def _forge_playbooks_root(workspace_root: str) -> str:
    return os.path.normpath(os.path.join(workspace_root, ".Forge", "playbooks"))


def _is_under_forge_playbooks(workspace_root: str, file_path: str) -> bool:
    root_pb = _forge_playbooks_root(workspace_root)
    fp_n = os.path.normpath(file_path)
    return fp_n == root_pb or fp_n.startswith(root_pb + os.sep)


def _playbook_load_parent_dir(workspace_root: str, file_path: str) -> Path:
    """Directory to pass as playbook_dir when reloading a file from disk."""
    if _is_under_forge_playbooks(workspace_root, file_path):
        return Path(_forge_playbooks_root(workspace_root))
    return Path(os.path.dirname(os.path.normpath(file_path)))


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


def _playbook_workspace_relative_path(runtime: Any, source: str) -> str | None:
    """Return path relative to workspace root, or None if source is outside the workspace."""
    root = os.path.normpath(runtime.config.workspace_mount_path_in_runtime)
    src = os.path.normpath(source)
    try:
        common = os.path.commonpath([root, src])
    except ValueError:
        return None
    if common != root:
        return None
    rel = os.path.relpath(src, root).replace("\\", "/")
    return rel if rel and not rel.startswith("..") else None


def _find_playbook(memory: Memory, name: str) -> tuple[Any, str] | tuple[None, None]:
    if name in memory.repo_playbooks:
        return memory.repo_playbooks[name], "repo"
    if name in memory.knowledge_playbooks:
        return memory.knowledge_playbooks[name], "knowledge"
    return None, None


@sub_router.put("/playbooks/{name:path}")
async def update_playbook(
    name: str,
    body: UpdatePlaybookRequest,
    conversation: ServerConversation = Depends(get_conversation),
) -> JSONResponse:
    """Write updated playbook content to the backing file in the conversation workspace."""
    try:
        if not conversation.runtime:
            return error(
                message="Runtime not ready yet, please try again",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="RUNTIME_NOT_READY",
            )
        memory = _get_conversation_memory(conversation)
        pb, kind = _find_playbook(memory, name)
        if pb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")

        rel = _playbook_workspace_relative_path(conversation.runtime, pb.source)
        if rel is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This playbook is not stored in the conversation workspace (cannot edit here).",
            )

        runtime = cast("Runtime", conversation.runtime)
        root = runtime.config.workspace_mount_path_in_runtime
        old_fp = os.path.normpath(os.path.join(root, rel))
        if not old_fp.startswith(os.path.normpath(root)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

        raw_new = (body.name or "").strip()
        new_key = _validate_playbook_name_key(raw_new) if raw_new else name
        if new_key != name and not _is_under_forge_playbooks(root, old_fp):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Renaming is only supported for playbooks under .Forge/playbooks",
            )

        if new_key != name:
            pb_root = _forge_playbooks_root(root)
            parts = tuple(PurePosixPath(new_key).parts)
            filename = f"{parts[-1]}.md"
            new_fp = os.path.normpath(os.path.join(pb_root, *parts[:-1], filename))
            if not new_fp.startswith(os.path.normpath(root)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
            if new_key in memory.repo_playbooks or new_key in memory.knowledge_playbooks:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A playbook with that name already exists",
                )
            if new_fp != old_fp:
                if os.path.exists(new_fp):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Target playbook path already exists",
                    )
                parent = os.path.dirname(new_fp)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                if not os.path.isfile(old_fp):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot rename: playbook file is missing",
                    )
                shutil.move(old_fp, new_fp)
            target_fp = new_fp
        else:
            target_fp = old_fp

        write_action = FileWriteAction(path=target_fp, content=body.content)
        await call_sync_from_async(runtime.run_action, write_action)

        load_dir = _playbook_load_parent_dir(root, target_fp)
        reloaded = BasePlaybook.load(Path(target_fp), load_dir)

        if kind == "repo":
            memory.repo_playbooks.pop(name, None)
            memory.repo_playbooks[reloaded.name] = reloaded
        else:
            memory.knowledge_playbooks.pop(name, None)
            memory.knowledge_playbooks[reloaded.name] = reloaded

        return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating playbook %s: %s", name, e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": f"Error updating playbook: {e}"},
        )


@sub_router.delete("/playbooks/{name:path}")
async def delete_playbook(
    name: str,
    conversation: ServerConversation = Depends(get_conversation),
) -> JSONResponse:
    """Remove playbook file from the workspace and unload it from session memory."""
    try:
        if not conversation.runtime:
            return error(
                message="Runtime not ready yet, please try again",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="RUNTIME_NOT_READY",
            )
        memory = _get_conversation_memory(conversation)
        pb, kind = _find_playbook(memory, name)
        if pb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")

        rel = _playbook_workspace_relative_path(conversation.runtime, pb.source)
        if rel is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This playbook is not stored in the conversation workspace (cannot delete here).",
            )

        root = conversation.runtime.config.workspace_mount_path_in_runtime
        full_path = os.path.normpath(os.path.join(root, rel))
        if not full_path.startswith(os.path.normpath(root)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

        if os.path.isfile(full_path):
            os.remove(full_path)

        if kind == "repo":
            del memory.repo_playbooks[name]
        else:
            del memory.knowledge_playbooks[name]

        return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting playbook %s: %s", name, e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": f"Error deleting playbook: {e}"},
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
    desc = getattr(k_agent.metadata, "description", None) or ""
    return PlaybookResponse(
        name=name,
        type="knowledge",
        content=k_agent.content,
        source=k_agent.source,
        description=str(desc),
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
        return [server.name for server in agent.metadata.mcp_tools.servers if server.type == "stdio"]
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


async def _load_completion_llm_config(
    request: Request, user_id: str | None
) -> tuple[LLMConfig | None, JSONResponse | None]:
    """Load LLM config from user settings. Returns (config, error_response)."""
    from backend.core.cache.async_smart_cache import AsyncSmartCache

    cache = AsyncSmartCache()
    user_settings_store = get_user_settings_store(request)
    if not user_settings_store:
        return None, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "User settings store not available."},
        )
    settings = await cache.get_user_settings(
        user_id or "anonymous", user_settings_store
    )
    if not settings or not settings.llm_model:
        settings = await user_settings_store.load()
    if not settings or not settings.llm_model:
        return None, JSONResponse(
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
    return llm_config, None


def _build_completion_success_content(result: CompletionResult) -> dict[str, Any]:
    """Build content dict for successful completion response."""
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
    return content


def _build_completion_error_response(exc: Exception) -> JSONResponse:
    """Build JSONResponse for completion exception."""
    error_type = ErrorRecoveryStrategy.classify_error(exc)
    logger.error("Completion error (%s): %s", error_type.value, exc, exc_info=True)
    status_map = {
        ErrorType.NETWORK_ERROR: status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorType.TIMEOUT_ERROR: status.HTTP_504_GATEWAY_TIMEOUT,
        ErrorType.PERMISSION_ERROR: status.HTTP_403_FORBIDDEN,
    }
    return JSONResponse(
        status_code=status_map.get(error_type, status.HTTP_500_INTERNAL_SERVER_ERROR),
        content={
            "error": format_error_message(exc, error_type),
            "errorType": error_type.value,
            "completion": "",
            "stopReason": "error",
        },
    )


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
    from backend.engines.orchestrator.file_verification_guard import (
        FileVerificationGuard,
    )

    llm_config, config_error = await _load_completion_llm_config(request, user_id)
    if config_error is not None:
        return config_error

    anti_hallucination = FileVerificationGuard()
    manager = require_conversation_manager()
    req = CompletionRequest(
        file_path=request_body.filePath,
        file_content=request_body.fileContent,
        language=request_body.language,
        position=request_body.position,
        prefix=request_body.prefix,
        suffix=request_body.suffix,
    )

    assert llm_config is not None
    try:
        result: CompletionResult = await _run_completion(
            req=req,
            conversation_sid=conversation.sid,
            user_id=user_id,
            llm_config=llm_config,
            manager=manager,
            anti_hallucination=anti_hallucination,
        )
        content = _build_completion_success_content(result)
        return JSONResponse(status_code=result.status_code, content=content)
    except HTTPException:
        raise
    except Exception as e:
        return _build_completion_error_response(e)
