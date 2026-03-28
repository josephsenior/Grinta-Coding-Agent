"""Service helpers for initializing conversations and orchestrating agent sessions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger
from backend.ledger.action.message import MessageAction
from backend.core.provider_types import (
    CustomSecretsWithTypeSchema,
    ProviderTokenType,
    ProviderToken,
    ProviderType,
)
from backend.gateway.session.conversation_init_data import ConversationInitData
from backend.gateway.app_accessors import (
    ConversationStoreImpl,
    SettingsStoreImpl,
    config,
    get_conversation_manager,
)
from backend.gateway.store_factory import (
    get_conversation_store_instance,
    get_settings_store_instance,
)
from backend.gateway.types import MissingSettingsError
from backend.persistence.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)
from backend.utils.conversation_summary import get_default_conversation_title

if TYPE_CHECKING:
    from backend.core.config.mcp_config import MCPConfig
    from backend.gateway.schemas.agent_loop_info import AgentLoopInfo


async def initialize_conversation(
    user_id: str | None,
    conversation_id: str | None,
    selected_repository: str | None,
    selected_branch: str | None,
    conversation_trigger: ConversationTrigger = ConversationTrigger.GUI,
    vcs_provider: ProviderType | None = None,
) -> ConversationMetadata | None:
    """Initialize a new conversation or retrieve existing one.

    Creates metadata for new conversations with generated IDs and titles.

    Args:
        user_id: User identifier
        conversation_id: Conversation ID (generates new if None)
        selected_repository: Repository for conversation
        selected_branch: Branch for conversation
        conversation_trigger: How conversation was triggered
        vcs_provider: Git provider type

    Returns:
        Conversation metadata or None if retrieval fails

    """
    if conversation_id is None:
        conversation_id = uuid.uuid4().hex
    conversation_store = await get_conversation_store_instance(
        ConversationStoreImpl, config, user_id
    )
    if not await conversation_store.exists(conversation_id):
        logger.info(
            "New conversation ID: %s",
            conversation_id,
            extra={"user_id": user_id, "session_id": conversation_id},
        )
        conversation_title = get_default_conversation_title(conversation_id)
        logger.info("Saving metadata for conversation %s", conversation_id)
        conversation_metadata = ConversationMetadata(
            trigger=conversation_trigger,
            conversation_id=conversation_id,
            title=conversation_title,
            user_id=user_id,
            selected_repository=selected_repository,
            selected_branch=selected_branch,
            vcs_provider=vcs_provider,
        )
        await conversation_store.save_metadata(conversation_metadata)
        return conversation_metadata
    try:
        return await conversation_store.get_metadata(conversation_id)
    except Exception as e:
        logger.warning(
            "Failed to get conversation metadata for %s: %s", conversation_id, e
        )
    return None


def _process_git_provider_tokens(
    vcs_provider_tokens: ProviderTokenType | None,
) -> ProviderTokenType:
    """Process and normalize git provider tokens.

    Args:
        vcs_provider_tokens: Raw provider tokens (dict, MappingProxy, or None)

    Returns:
        Normalized provider tokens as MappingProxyType

    """
    if not vcs_provider_tokens:
        return MappingProxyType({})

    if isinstance(vcs_provider_tokens, dict):
        return MappingProxyType(vcs_provider_tokens)

    return vcs_provider_tokens


def _process_custom_secrets(
    custom_secrets: CustomSecretsWithTypeSchema | Any | None,
) -> MappingProxyType:
    """Process and normalize custom secrets.

    Args:
        custom_secrets: Raw custom secrets (UserSecrets, dict, or None)

    Returns:
        Normalized custom secrets as MappingProxyType

    """
    from backend.persistence.data_models.user_secrets import UserSecrets

    if not custom_secrets:
        return MappingProxyType({})

    if isinstance(custom_secrets, UserSecrets):
        # UserSecrets.custom_secrets is already a MappingProxyType
        secrets_dict = custom_secrets.custom_secrets
        return MappingProxyType(dict(secrets_dict))

    if isinstance(custom_secrets, dict):
        return MappingProxyType(custom_secrets)

    # If it's already a MappingProxyType, return it
    if isinstance(custom_secrets, MappingProxyType):
        return custom_secrets

    # Fallback: wrap in MappingProxyType
    return MappingProxyType({})


def _normalize_provider_list(
    providers_set: Sequence[ProviderType | str] | None,
) -> list[ProviderType]:
    """Normalize provider list to ProviderType enum."""
    normalized_providers: list[ProviderType] = []
    for provider in providers_set or []:
        if isinstance(provider, ProviderType):
            normalized_providers.append(provider)
        else:
            try:
                normalized_providers.append(ProviderType(provider))
            except Exception:
                continue
    return normalized_providers


def _get_normalized_provider_tokens(
    provider_tokens: ProviderTokenType | None,
    default_tokens: ProviderTokenType | None,
) -> ProviderTokenType | None:
    """Get normalized provider tokens, falling back to defaults if needed."""
    normalized = _process_git_provider_tokens(provider_tokens)
    return normalized if normalized else default_tokens


def _ensure_provider_tokens_for_providers(
    normalized_tokens: ProviderTokenType | None,
    providers_set: Sequence[ProviderType | str] | None,
    user_id: str | None,
) -> ProviderTokenType:
    """Ensure tokens exist for all requested providers."""
    normalized_providers = _normalize_provider_list(providers_set)
    if not normalized_providers:
        return normalized_tokens or MappingProxyType({})

    token_dict = dict(normalized_tokens) if normalized_tokens is not None else {}
    for provider in normalized_providers:
        token_dict.setdefault(provider, ProviderToken(token=None, user_id=user_id))
    return MappingProxyType(token_dict)


def _build_session_init_args(
    settings: Any,
    conversation_metadata: ConversationMetadata,
    vcs_provider_tokens: ProviderTokenType | None,
    custom_secrets: CustomSecretsWithTypeSchema | None,
    conversation_instructions: str | None,
    mcp_config: MCPConfig | None,
) -> dict[str, Any]:
    """Build session initialization arguments from various sources.

    Args:
        settings: User settings
        conversation_metadata: Conversation metadata
        vcs_provider_tokens: Provider tokens
        custom_secrets: Custom secrets
        conversation_instructions: Custom instructions
        mcp_config: MCP configuration

    Returns:
        Dictionary of session initialization arguments

    """
    session_init_args: dict[str, Any] = {**settings.__dict__}

    # Add provider tokens and secrets
    session_init_args["vcs_provider_tokens"] = _process_git_provider_tokens(
        vcs_provider_tokens
    )
    session_init_args["custom_secrets"] = _process_custom_secrets(custom_secrets)

    # Add conversation metadata
    session_init_args["selected_repository"] = conversation_metadata.selected_repository
    session_init_args["selected_branch"] = conversation_metadata.selected_branch
    session_init_args["vcs_provider"] = conversation_metadata.vcs_provider
    session_init_args["conversation_instructions"] = conversation_instructions

    # Add optional MCP config
    if mcp_config:
        session_init_args["mcp_config"] = mcp_config

    return session_init_args


def _create_initial_message_action(
    initial_user_msg: str | None,
    image_urls: list[str] | None,
) -> MessageAction | None:
    """Create initial message action if user message or images provided.

    Args:
        initial_user_msg: Initial user message
        image_urls: Initial image URLs

    Returns:
        MessageAction or None if no message or images

    """
    if not initial_user_msg and not image_urls:
        return None

    return MessageAction(content=initial_user_msg or "", image_urls=image_urls or [])


async def start_conversation(
    user_id: str | None,
    vcs_provider_tokens: ProviderTokenType | None,
    custom_secrets: CustomSecretsWithTypeSchema | None,
    initial_user_msg: str | None,
    image_urls: list[str] | None,
    replay_json: str | None,
    conversation_id: str,
    conversation_metadata: ConversationMetadata,
    conversation_instructions: str | None,
    mcp_config: MCPConfig | None = None,
) -> AgentLoopInfo:
    """Start an agent loop for a conversation with user settings and init data.

    Loads user settings, validates API keys, initializes conversation data,
    and starts the agent loop.

    Args:
        user_id: User identifier
        vcs_provider_tokens: Git provider authentication tokens
        custom_secrets: Custom user secrets
        initial_user_msg: Initial message from user
        image_urls: Initial image URLs
        replay_json: JSON for replaying conversation
        conversation_id: Conversation identifier
        conversation_metadata: Conversation metadata
        conversation_instructions: Custom instructions for conversation
        mcp_config: MCP configuration

    Returns:
        Agent loop information

    Raises:
        LLMAuthenticationError: If LLM API key invalid
        MissingSettingsError: If user settings not found

    """
    logger.info(
        "Creating conversation",
        extra={
            "signal": "create_conversation",
            "user_id": user_id,
            "trigger": conversation_metadata.trigger,
        },
    )

    # Load and validate settings
    logger.info("Loading settings")
    settings_store = await get_settings_store_instance(
        SettingsStoreImpl, config, user_id
    )
    settings = await settings_store.load()
    logger.info("Settings loaded")

    if not settings:
        logger.warning("Settings not present, not starting conversation")
        raise MissingSettingsError("Settings not found")

    # Build session initialization arguments
    session_init_args = _build_session_init_args(
        settings,
        conversation_metadata,
        vcs_provider_tokens,
        custom_secrets,
        conversation_instructions,
        mcp_config,
    )

    # Create conversation init data
    conversation_init_data = ConversationInitData(**session_init_args)

    # Start agent loop
    logger.info(
        "Starting agent loop for conversation %s",
        conversation_id,
        extra={"user_id": user_id, "session_id": conversation_id},
    )

    initial_message_action = _create_initial_message_action(
        initial_user_msg, image_urls
    )

    manager = get_conversation_manager()
    if manager is None:
        raise RuntimeError("Conversation manager is not initialized")
    agent_loop_info = await manager.maybe_start_agent_loop(
        conversation_id,
        conversation_init_data,
        user_id,
        initial_user_msg=initial_message_action,
        replay_json=replay_json,
    )

    logger.info(
        "Finished initializing conversation %s", agent_loop_info.conversation_id
    )
    return agent_loop_info


async def create_new_conversation(
    user_id: str | None,
    vcs_provider_tokens: ProviderTokenType | None,
    custom_secrets: CustomSecretsWithTypeSchema | None,
    selected_repository: str | None,
    selected_branch: str | None,
    initial_user_msg: str | None,
    image_urls: list[str] | None,
    replay_json: str | None,
    conversation_instructions: str | None = None,
    conversation_trigger: ConversationTrigger = ConversationTrigger.GUI,
    vcs_provider: ProviderType | None = None,
    conversation_id: str | None = None,
    mcp_config: MCPConfig | None = None,
) -> AgentLoopInfo:
    """Create and start a new conversation end-to-end.

    Initializes conversation metadata and starts agent loop in one operation.

    Args:
        user_id: User identifier
        vcs_provider_tokens: Git provider tokens
        custom_secrets: Custom secrets
        selected_repository: Repository for conversation
        selected_branch: Branch for conversation
        initial_user_msg: Initial message
        image_urls: Initial images
        replay_json: Replay data
        conversation_instructions: Custom instructions
        conversation_trigger: How conversation was triggered
        vcs_provider: Git provider type
        conversation_id: Optional conversation ID
        mcp_config: MCP configuration

    Returns:
        Agent loop information

    Raises:
        ValueError: If conversation initialization fails

    """
    conversation_metadata = await initialize_conversation(
        user_id,
        conversation_id,
        selected_repository,
        selected_branch,
        conversation_trigger,
        vcs_provider,
    )
    if conversation_metadata is None:
        raise ValueError("Failed to initialize conversation metadata")

    return await start_conversation(
        user_id=user_id,
        vcs_provider_tokens=vcs_provider_tokens,
        custom_secrets=custom_secrets,
        initial_user_msg=initial_user_msg,
        image_urls=image_urls,
        replay_json=replay_json,
        conversation_id=conversation_metadata.conversation_id,
        conversation_metadata=conversation_metadata,
        conversation_instructions=conversation_instructions,
        mcp_config=mcp_config,
    )


def create_provider_tokens_object(
    providers_set: list[ProviderType],
) -> ProviderTokenType:
    """Create provider tokens object for the given providers."""
    provider_information: dict[ProviderType, ProviderToken] = {
        provider: ProviderToken(token=None, user_id=None) for provider in providers_set
    }
    return MappingProxyType(provider_information)


async def setup_init_conversation_settings(
    user_id: str | None,
    conversation_id: str,
    providers_set: Sequence[ProviderType | str] | None = None,
    provider_tokens: ProviderTokenType | None = None,
) -> ConversationInitData:
    """Prepare conversation settings for joining an existing session.

    Args:
        user_id: Authenticated user identifier.
        conversation_id: The conversation identifier to join.
        providers_set: Optional list of providers requiring token placeholders.
        provider_tokens: Optional provider tokens supplied by caller.

    Returns:
        ConversationInitData containing session settings.

    Raises:
        MissingSettingsError: If user settings cannot be loaded.
        RuntimeError: If conversation metadata is unavailable.
    """
    conversation_store = await get_conversation_store_instance(
        ConversationStoreImpl, config, user_id
    )
    conversation_metadata = await conversation_store.get_metadata(conversation_id)
    if not conversation_metadata:
        raise RuntimeError(f"Conversation metadata not found for {conversation_id}")

    settings_store = await get_settings_store_instance(
        SettingsStoreImpl, config, user_id
    )
    settings = await settings_store.load()

    # If no user settings exist, try to load from settings.json
    if settings is None:
        from backend.persistence.data_models.settings import Settings

        try:
            settings = Settings.from_config()
            if settings:
                settings = settings.merge_with_config_settings()
                logger.info(
                    "Loaded default settings from settings.json for WebSocket connection (user_id: %s)",
                    user_id,
                )
        except Exception as e:
            logger.error("Failed to load settings from config: %s", e)

    if settings is None:
        raise MissingSettingsError(
            "Settings not found (neither user settings nor settings.json)"
        )

    # Validate API key for the selected model
    # API key validation is handled by LLMConfig validation
    # No need for separate validation function

    normalized_tokens = _get_normalized_provider_tokens(
        provider_tokens, settings.secrets_store.provider_tokens
    )
    normalized_tokens = _ensure_provider_tokens_for_providers(
        normalized_tokens, providers_set, user_id
    )

    session_init_args = _build_session_init_args(
        settings,
        conversation_metadata,
        normalized_tokens,
        settings.secrets_store.custom_secrets,
        conversation_instructions=None,
        mcp_config=settings.mcp_config,
    )
    return ConversationInitData(**session_init_args)
