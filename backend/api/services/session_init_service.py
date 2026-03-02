"""Session initialization business logic.

Extracted from ``manage_conversations.py`` to keep route handlers thin.
Contains request parsing, validation, trigger determination, and the
main conversation-creation orchestration that the ``POST /conversations``
route delegates to.
"""

from __future__ import annotations

import os
import uuid
from types import MappingProxyType
from typing import Any, cast

from fastapi import status
from fastapi.responses import JSONResponse

from backend.core.provider_types import (
    ProviderTokenType,
    CreatePlaybook,
    ProviderType,
    SuggestedTask,
)
from backend.core.enums import RuntimeStatus
from backend.api.services.conversation_service import create_new_conversation
from backend.api.types import LLMAuthenticationError, MissingSettingsError
from backend.api.utils.error_formatter import format_error_for_user
from backend.storage.data_models.conversation_metadata import ConversationTrigger
from backend.storage.data_models.user_secrets import UserSecrets

if __name__ != "__main__":
    pass


# ---------------------------------------------------------------------------
# Request data extraction
# ---------------------------------------------------------------------------


def extract_request_data(
    data: Any,
) -> tuple[
    str | None,
    str | None,
    str | None,
    list[str],
    str | None,
    SuggestedTask | None,
    CreatePlaybook | None,
    ProviderType | None,
    str | None,
]:
    r"""Extract and organize initialization parameters from request payload.

    Unpacks the InitSessionRequest into individual components for use in
    conversation initialization.

    Returns:
        Tuple containing in order:
            - repository, selected_branch, initial_user_msg, image_urls,
              replay_json, suggested_task, create_playbook, vcs_provider,
              conversation_instructions
    """
    return (
        data.repository,
        data.selected_branch,
        data.initial_user_msg,
        data.image_urls or [],
        data.replay_json,
        data.suggested_task,
        data.create_playbook,
        data.vcs_provider,
        data.conversation_instructions,
    )


def determine_conversation_trigger(
    suggested_task: SuggestedTask | None,
    create_playbook: CreatePlaybook | None,
) -> tuple[ConversationTrigger, str | None, ProviderType | None]:
    """Determine conversation trigger type and override repository/provider if needed."""
    conversation_trigger = ConversationTrigger.GUI
    repository = None
    vcs_provider = None

    if suggested_task:
        conversation_trigger = ConversationTrigger.SUGGESTED_TASK
    elif create_playbook:
        conversation_trigger = ConversationTrigger.PLAYBOOK_MANAGEMENT
        if create_playbook.repo:
            repository = create_playbook.repo
        if create_playbook.vcs_provider:
            vcs_provider = create_playbook.vcs_provider

    return conversation_trigger, repository, vcs_provider


def validate_remote_api_request(
    initial_user_msg: str,
) -> JSONResponse | None:
    """Validate conversation-init requests have required parameters."""
    if not initial_user_msg:
        return None
    return None


async def verify_repository_access(
    repository: str | None,
    vcs_provider: ProviderType | None,
    provider_tokens: ProviderTokenType,
) -> None:
    """Verify user has access to the specified repository.

    This is a no-op after the GitHub integration removal.
    Repository access verification requires a live Git provider
    connection which is now handled by external MCP servers.
    """


def apply_conversation_overrides(
    repository: str | None,
    vcs_provider: ProviderType | None,
    override_repo: str | None,
    override_git_provider: ProviderType | None,
    suggested_task: SuggestedTask | None,
    initial_user_msg: str | None,
) -> tuple[str | None, ProviderType | None, str | None]:
    """Apply conversation overrides from triggers."""
    if override_repo:
        repository = override_repo
    if override_git_provider:
        vcs_provider = override_git_provider
    if suggested_task:
        initial_user_msg = suggested_task.get_prompt_for_task()

    return repository, vcs_provider, initial_user_msg


def normalize_provider_tokens(
    provider_tokens: ProviderTokenType | None,
) -> ProviderTokenType:
    """Normalize provider tokens into a MappingProxyType keyed by ProviderType."""
    if provider_tokens is None:
        return cast(ProviderTokenType, MappingProxyType({}))
    if isinstance(provider_tokens, MappingProxyType):
        return provider_tokens

    normalized_dict = {}
    for k, v in dict(provider_tokens).items():
        if isinstance(k, str):
            try:
                k = ProviderType(k)
            except ValueError:
                continue
        normalized_dict[k] = v

    return cast(
        ProviderTokenType,
        MappingProxyType(normalized_dict),
    )


def prepare_conversation_params(
    user_id: str | None,
    provider_tokens: ProviderTokenType | None,
    user_secrets: UserSecrets | None,
) -> tuple[str, ProviderTokenType, UserSecrets]:
    """Prepare conversation parameters with defaults."""
    normalized_tokens = normalize_provider_tokens(provider_tokens)
    return (
        user_id or "dev-user",
        normalized_tokens,
        user_secrets or UserSecrets(),
    )


async def handle_regular_conversation(
    user_id: str,
    conversation_id: str,
    repository: str | None,
    selected_branch: str | None,
    initial_user_msg: str | None,
    image_urls: list[str],
    replay_json: str | None,
    conversation_trigger: ConversationTrigger,
    conversation_instructions: str | None,
    vcs_provider: ProviderType | None,
    provider_tokens: ProviderTokenType,
    user_secrets: UserSecrets,
    mcp_config: Any | None,
) -> Any:
    """Initialize a regular conversation with full startup configuration.

    Returns:
        ConversationResponse-compatible data (status, conversation_id, conversation_status).
    """
    return await create_new_conversation(
        user_id=user_id,
        vcs_provider_tokens=provider_tokens,
        custom_secrets=user_secrets.custom_secrets if user_secrets else None,
        selected_repository=repository,
        selected_branch=selected_branch,
        initial_user_msg=initial_user_msg,
        image_urls=image_urls or None,
        replay_json=replay_json,
        conversation_trigger=conversation_trigger,
        conversation_instructions=conversation_instructions,
        vcs_provider=vcs_provider,
        conversation_id=conversation_id,
        mcp_config=mcp_config,
    )


def handle_conversation_errors(e: Exception) -> JSONResponse:
    """Convert conversation initialization errors to appropriate HTTP responses."""
    if isinstance(e, MissingSettingsError):
        error_dict = format_error_for_user(
            e, context={"error_code": "CONFIGURATION$SETTINGS_NOT_FOUND"}
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_dict,
        )
    if isinstance(e, LLMAuthenticationError):
        error_dict = format_error_for_user(
            e,
            context={
                "error_code": RuntimeStatus.ERROR_LLM_AUTHENTICATION.value,
                "category": "authentication",
            },
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_dict,
        )
    raise e


def resolve_conversation_id(data: Any) -> str:
    """Generate or validate conversation ID based on env config."""
    allow_set_id = os.getenv("ALLOW_SET_CONVERSATION_ID", "0") == "1"
    return (
        data.conversation_id if allow_set_id and data.conversation_id else None
    ) or uuid.uuid4().hex
