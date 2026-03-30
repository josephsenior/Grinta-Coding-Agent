"""Routes for creating, listing, and managing App conversations and sessions.

Business logic is delegated to:
- ``session_init_service``   – conversation creation / init orchestration
- ``conversation_query_service`` – listing, search, detail, delete
- ``prompt_service``         – remember-prompt generation
"""

from __future__ import annotations

import traceback
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Imports needed for InitSessionRequest model_rebuild
from backend.core.config.mcp_config import MCPConfig
from backend.core.logger import app_logger as logger
from backend.core.provider_types import (
    ProviderTokenType,
    CreatePlaybook,
    ProviderType,
    SuggestedTask,
)
from backend.gateway.services.conversation_mutation_service import (
    search_playbook_conversations,
    start_agent_loop,
    stop_agent_loop,
    update_conversation_title,
)
from backend.gateway.services.conversation_query_service import (
    delete_all_conversations,
    delete_conversation_entry,
    get_conversation_details,
)
from backend.gateway.services.conversation_query_service import (
    search_conversations as _search_conversations_impl,
)
from backend.gateway.services.prompt_service import build_remember_prompt
from backend.gateway.services.session_init_service import (
    apply_conversation_overrides,
    determine_conversation_trigger,
    extract_request_data,
    handle_conversation_errors,
    handle_regular_conversation,
    prepare_conversation_params,
    resolve_conversation_id,
    validate_remote_api_request,
    verify_repository_access,
)
from backend.gateway.services.service_dependencies import get_file_store
from backend.gateway.types import LLMAuthenticationError, MissingSettingsError
from backend.gateway.user_auth import (
    get_provider_tokens,
    get_user_id,
    get_user_secrets,
    get_user_settings,
    get_user_settings_store,
)
from backend.gateway.utils import get_conversation as get_conversation_metadata
from backend.gateway.utils import (
    get_conversation_store,
    validate_conversation_id,
)
from backend.gateway.utils.responses import error
from backend.persistence.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)
from backend.persistence.data_models.conversation_status import ConversationStatus
from backend.persistence.data_models.settings import Settings
from backend.persistence.data_models.user_secrets import UserSecrets

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

sub_router = APIRouter(prefix="/api/v1", tags=["conversations"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class InitSessionRequest(BaseModel):
    """Request payload for creating or resuming a conversation session."""

    repository: str | None = Field(None, description="Repository identifier")
    vcs_provider: ProviderType | None = Field(None, description="Git provider type")
    selected_branch: str | None = Field(None, description="Selected branch name")
    initial_user_msg: str | None = Field(None, description="Initial user message")
    image_urls: list[str] | None = Field(None, description="List of image URLs")
    replay_json: str | None = Field(
        None, description="JSON string for replaying conversation"
    )
    suggested_task: SuggestedTask | None = Field(
        None, description="Suggested task object"
    )
    create_playbook: CreatePlaybook | None = Field(
        None, description="Playbook creation parameters"
    )
    conversation_instructions: str | None = Field(
        None, description="Custom conversation instructions"
    )
    mcp_config: MCPConfig | None = Field(None, description="MCP server configuration")
    conversation_id: str | None = Field(
        None, description="Conversation ID (if resuming)"
    )
    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "repository",
        "selected_branch",
        "initial_user_msg",
        "conversation_instructions",
        "conversation_id",
    )
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        if v is not None:
            from backend.core.type_safety.type_safety import validate_non_empty_string

            return validate_non_empty_string(v, name="field")
        return v


InitSessionRequest.model_rebuild()


class ConversationResponse(BaseModel):
    """Standard response payload for conversation management endpoints."""

    status: str = Field(..., min_length=1, description="Response status")
    conversation_id: str = Field(..., min_length=1, description="Conversation ID")
    message: str | None = Field(None, description="Optional message")
    conversation_status: ConversationStatus | None = Field(
        None, description="Conversation status"
    )

    @field_validator("status", "conversation_id")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


class ProvidersSetModel(BaseModel):
    """Wrapper for optional provider list supplied when starting a conversation."""

    providers_set: list[ProviderType] | None = None


class UpdateConversationRequest(BaseModel):
    """Request model for updating conversation metadata."""

    title: str = Field(
        ..., min_length=1, max_length=200, description="New conversation title"
    )
    model_config = ConfigDict(extra="forbid")

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="title")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@sub_router.post("/conversations", response_model=ConversationResponse, summary="Create or resume a conversation")
async def new_conversation(
    request: Request,
    data: InitSessionRequest,
    user_id: Annotated[str | None, Depends(get_user_id)] = None,
    provider_tokens: Annotated[
        ProviderTokenType | None, Depends(get_provider_tokens)
    ] = None,
    user_secrets: Annotated[UserSecrets | None, Depends(get_user_secrets)] = None,
    settings: Annotated[Settings | None, Depends(get_user_settings)] = None,
) -> Any:
    """Initialize a new session or join an existing one."""
    logger.info("initializing_new_conversation - parsed data: %s", data)

    if not settings:
        logger.warning(
            "Settings not found for user_id: %s, attempting to load from config",
            user_id,
        )
        try:
            settings = Settings.from_config()
            if settings:
                settings = settings.merge_with_config_settings()
                logger.info(
                    "Loaded default settings from settings.json for user_id: %s", user_id
                )
        except Exception as e:
            logger.error("Failed to load settings from config: %s", e)

    if not settings:
        logger.error("No settings available for user_id: %s", user_id)
        return error(
            message="Settings not found. Please configure your LLM settings before creating a conversation.",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="CONFIGURATION$SETTINGS_NOT_FOUND",
            request=request,
        )

    (
        repository,
        selected_branch,
        initial_user_msg,
        image_urls,
        replay_json,
        suggested_task,
        create_playbook,
        vcs_provider,
        conversation_instructions,
    ) = extract_request_data(data)

    conversation_trigger, override_repo, override_git_provider = (
        determine_conversation_trigger(suggested_task, create_playbook)
    )

    repository, vcs_provider, initial_user_msg = apply_conversation_overrides(
        repository,
        vcs_provider,
        override_repo,
        override_git_provider,
        suggested_task,
        initial_user_msg,
    )

    if error_response := validate_remote_api_request(initial_user_msg or ""):
        return error_response

    user_id, provider_tokens, user_secrets = prepare_conversation_params(
        user_id, provider_tokens, user_secrets
    )

    try:
        if repository:
            await verify_repository_access(repository, vcs_provider, provider_tokens)

        conversation_id = resolve_conversation_id(data)

        agent_loop_info = await handle_regular_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            repository=repository,
            selected_branch=selected_branch,
            initial_user_msg=initial_user_msg,
            image_urls=image_urls,
            replay_json=replay_json,
            conversation_trigger=conversation_trigger,
            conversation_instructions=conversation_instructions,
            vcs_provider=vcs_provider,
            provider_tokens=provider_tokens,
            user_secrets=user_secrets,
            mcp_config=data.mcp_config,
        )

        return ConversationResponse(
            status="ok",
            conversation_id=conversation_id,
            message=None,
            conversation_status=agent_loop_info.status,
        )
    except Exception as e:
        logger.exception("Failed to initialize conversation: %s", e)
        with open("crash_new_conv.log", "w") as f:
            traceback.print_exc(file=f)
        return handle_conversation_errors(e)


@sub_router.get("/conversations/test")
async def test_conversations_endpoint() -> JSONResponse:
    """Test endpoint to verify routing is working."""
    return JSONResponse(
        content={
            "status": "test_working",
            "message": "conversations endpoint is accessible",
        }
    )


@sub_router.get("/conversations/simple")
async def simple_conversations_endpoint() -> dict:
    """Simple endpoint without dependencies to test routing."""
    return {"status": "simple_working", "count": 1}


@sub_router.get("/conversations", response_model=None, summary="List conversations with optional filters")
async def search_conversations_route(
    request: Request,
    page_id: str | None = Query(None, description="Page cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results per page"),
    selected_repository: str | None = Query(None, description="Filter by repository"),
    conversation_trigger: ConversationTrigger | None = Query(
        None, description="Filter by conversation trigger type"
    ),
) -> Any:
    """HTTP endpoint to paginate conversation metadata with optional filters."""
    try:
        user_id = get_user_id(request)
        conversation_store = await get_conversation_store(request)
        normalized_page_id = (
            page_id if isinstance(page_id, str) and page_id.strip() else None
        )
        normalized_repository = (
            selected_repository
            if isinstance(selected_repository, str) and selected_repository.strip()
            else None
        )

        return await _search_conversations_impl(
            page_id=normalized_page_id,
            limit=limit,
            selected_repository=normalized_repository,
            conversation_trigger=conversation_trigger,
            user_id=user_id,
            conversation_store=conversation_store,
        )
    except ValueError as e:
        logger.error("Validation error in conversations endpoint: %s", e)
        return error(
            message=f"Invalid request parameters: {str(e)}",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_PARAMETERS",
            request=request,
        )
    except Exception as e:
        logger.error("Error in conversations endpoint: %s", e, exc_info=True)
        return error(
            message="An error occurred while fetching conversations",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            request=request,
        )


# Alias for tests expecting the function directly
search_conversations = _search_conversations_impl


@sub_router.get("/conversations/{conversation_id}", response_model=None, summary="Get conversation details")
async def _get_conversation_route(
    request: Request,
    conversation_id: str = Depends(validate_conversation_id),
) -> Any:
    user_id = get_user_id(request)
    conversation_store = await get_conversation_store(request)
    result = await get_conversation_details(
        conversation_id, conversation_store, user_id
    )
    if result is None:
        return JSONResponse(
            status_code=404, content={"error": "Conversation not found"}
        )
    return result


@sub_router.delete("/conversations/{conversation_id}")
async def _delete_conversation_route(
    request: Request,
    conversation_id: str = Depends(validate_conversation_id),
) -> bool:
    user_id = get_user_id(request)
    conversation_store = await get_conversation_store(request)
    return await delete_conversation_entry(conversation_id, user_id, conversation_store)


@sub_router.delete("/conversations")
async def _delete_all_conversations_route(
    request: Request,
) -> bool:
    """Delete all conversations for the user."""
    user_id = get_user_id(request)
    conversation_store = await get_conversation_store(request)
    return await delete_all_conversations(user_id, conversation_store)


@sub_router.get("/conversations/{conversation_id}/remember-prompt")
async def get_prompt(
    event_id: int,
    conversation_id: Annotated[str, Depends(validate_conversation_id)],
    user_settings: Annotated[Any, Depends(get_user_settings_store)],
    metadata: Annotated[ConversationMetadata, Depends(get_conversation_metadata)],
    file_store: Annotated[Any, Depends(get_file_store)],
) -> JSONResponse:
    """Generate a prompt for remembering conversation context at specific event."""
    prompt = await build_remember_prompt(
        conversation_id=conversation_id,
        event_id=event_id,
        user_id=metadata.user_id,
        user_settings_store=user_settings,
        file_store=file_store,
    )
    return JSONResponse({"status": "success", "prompt": prompt})


@sub_router.post("/conversations/{conversation_id}/start", response_model=ConversationResponse, summary="Start agent loop")
async def start_conversation(
    providers_set: ProvidersSetModel,
    conversation_id: str = Depends(validate_conversation_id),
    user_id: str = Depends(get_user_id),
    provider_tokens: Annotated[
        ProviderTokenType | None, Depends(get_provider_tokens)
    ] = None,
    settings: Settings = Depends(get_user_settings),
    conversation_store: Annotated[Any | None, Depends(get_conversation_store)] = None,
) -> Any:
    """Start an agent loop for a conversation."""
    logger.info("=== START CONVERSATION ENDPOINT CALLED ===")
    logger.info("conversation_id: %s", conversation_id)
    try:
        result = await start_agent_loop(
            conversation_id=conversation_id,
            user_id=user_id,
            provider_tokens=provider_tokens,
            providers_list=providers_set.providers_set or [],
            conversation_store=conversation_store,
        )
        if not result.ok:
            return error(
                message=result.error_message or "Start failed",
                status_code=status.HTTP_404_NOT_FOUND,
                error_code=result.error_code or "START_CONVERSATION_ERROR",
                conversation_id=conversation_id,
            )
        return ConversationResponse(
            status="ok",
            conversation_id=conversation_id,
            message=result.message,
            conversation_status=result.conversation_status,
        )
    except (LLMAuthenticationError, MissingSettingsError) as e:
        return handle_conversation_errors(e)
    except Exception as e:
        logger.error(
            "Error starting conversation %s: %s",
            conversation_id,
            str(e),
            extra={"session_id": conversation_id},
        )
        return error(
            message=f"Failed to start conversation: {e!s}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="START_CONVERSATION_ERROR",
            conversation_id=conversation_id,
        )


@sub_router.post("/conversations/{conversation_id}/stop", response_model=ConversationResponse, summary="Stop agent loop")
async def stop_conversation(
    conversation_id: Annotated[str, Depends(validate_conversation_id)],
    user_id: Annotated[str, Depends(get_user_id)],
) -> Any:
    """Stop an agent loop for a conversation."""
    logger.info("Stopping conversation: %s", conversation_id)
    try:
        result = await stop_agent_loop(conversation_id, user_id)
        return ConversationResponse(
            status="ok",
            conversation_id=conversation_id,
            message=result.message,
            conversation_status=result.conversation_status,
        )
    except Exception as e:
        logger.error(
            "Error stopping conversation %s: %s",
            conversation_id,
            str(e),
            extra={"session_id": conversation_id},
        )
        return error(
            message=f"Failed to stop conversation: {e!s}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="STOP_CONVERSATION_ERROR",
            conversation_id=conversation_id,
        )


@sub_router.patch("/conversations/{conversation_id}", response_model=bool)
async def update_conversation(
    data: UpdateConversationRequest,
    conversation_id: Annotated[str, Depends(validate_conversation_id)],
    user_id: Annotated[str | None, Depends(get_user_id)],
    conversation_store: Annotated[Any | None, Depends(get_conversation_store)] = None,
) -> Any:
    """Update conversation metadata (title)."""
    logger.info(
        "Updating conversation %s with title: %s",
        conversation_id,
        data.title,
        extra={"session_id": conversation_id, "user_id": user_id},
    )
    try:
        result = await update_conversation_title(
            conversation_id=conversation_id,
            new_title=data.title,
            user_id=user_id,
            conversation_store=conversation_store,
        )
        if not result.ok:
            status_code = (
                status.HTTP_404_NOT_FOUND
                if result.error_code == "CONVERSATION$NOT_FOUND"
                else status.HTTP_403_FORBIDDEN
            )
            return error(
                message=result.error_message or "Update failed",
                status_code=status_code,
                error_code=result.error_code or "CONVERSATION$UPDATE_ERROR",
            )
        return True
    except Exception as e:
        logger.error(
            "Error updating conversation %s: %s",
            conversation_id,
            str(e),
            extra={"session_id": conversation_id},
        )
        return error(
            message=f"Failed to update conversation: {e!s}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="CONVERSATION$UPDATE_ERROR",
        )


@sub_router.get("/playbook-management/conversations")
async def get_playbook_management_conversations(
    selected_repository: str,
    page_id: str | None = None,
    limit: int = 20,
    conversation_store: Annotated[Any | None, Depends(get_conversation_store)] = None,
    provider_tokens: Annotated[
        ProviderTokenType | None, Depends(get_provider_tokens)
    ] = None,
) -> Any:
    """Get conversations for the playbook management page with pagination."""
    return await search_playbook_conversations(
        selected_repository=selected_repository,
        page_id=page_id,
        limit=limit,
        conversation_store=conversation_store,
        provider_tokens=provider_tokens,
    )
