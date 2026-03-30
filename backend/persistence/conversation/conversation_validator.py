"""Conversation access validation interfaces and default helper factory."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Literal

from backend.core.config.config_loader import load_app_config
from backend.core.logger import app_logger as logger
from backend.gateway.config.server_config import ServerConfig
from backend.gateway.user_auth import get_current_user_id
from backend.persistence.conversation.conversation_store import ConversationStore
from backend.persistence.data_models.conversation_metadata import ConversationMetadata
from backend.utils.conversation_summary import get_default_conversation_title
from backend.utils.import_utils import get_impl


class ConversationAccessDenied(Exception):
    """Raised when a user does not own the requested conversation (strict mode)."""


class ConversationValidator:
    """Validates conversation access with configurable strictness.

    Modes (configured via ``security.validation_mode`` in config or the
    ``APP_VALIDATION_MODE`` env-var override):

    * **permissive** (default): No ownership check; anonymous access
      auto-creates metadata.  Ideal for single-user / local-first setups.
    * **strict**: Rejects anonymous (``None``) user_id and verifies the
      caller owns the conversation.

    Extension point: set ``APP_CONVERSATION_VALIDATOR_CLS`` to a
    fully-qualified class name to replace this implementation entirely.
    """

    def __init__(self, mode: Literal["permissive", "strict"] | None = None) -> None:
        if mode is not None:
            self._mode = mode
        else:
            # Env-var override > config value > default
            env_mode = os.environ.get("APP_VALIDATION_MODE")
            if env_mode in ("permissive", "strict"):
                self._mode = env_mode  # type: ignore[assignment]
            else:
                try:
                    config = load_app_config()
                    self._mode = config.security.validation_mode
                except Exception:
                    self._mode = "permissive"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate(
        self,
        conversation_id: str,
        cookies_str: str,
        authorization_header: str | None = None,
    ) -> str | None:
        """Validate conversation access and return user ID.

        In *permissive* mode the caller always gets through and metadata
        is auto-created when missing.

        In *strict* mode:
        - ``user_id`` is derived from the authorization header (sub-classes
          should override ``_extract_user_id`` for real token parsing).
        - If ``user_id`` is ``None``, access is denied.
        - If metadata already exists and belongs to another user,
          ``ConversationAccessDenied`` is raised.

        Returns:
            The validated ``user_id``.

        Raises:
            ConversationAccessDenied: In strict mode when access is rejected.
        """
        user_id: str | None = self._extract_user_id(authorization_header)

        if self._mode == "strict":
            return await self._validate_strict(conversation_id, user_id)

        # Permissive: when the socket is anonymous, use the same default user id as
        # REST (`get_user_id` / `get_current_user_id`, e.g. oss_user). Otherwise
        # metadata and events were stored under `sessions/` or `users/dev-user/`
        # while the API listed and loaded history under `users/oss_user/`, so the
        # UI saw an empty thread and replay logged "Replayed 0 events".
        effective_id = user_id or get_current_user_id()
        await self._ensure_metadata_exists(conversation_id, effective_id)
        return effective_id

    # ------------------------------------------------------------------
    # Strict-mode helpers
    # ------------------------------------------------------------------

    async def _validate_strict(
        self, conversation_id: str, user_id: str | None
    ) -> str | None:
        if user_id is None:
            raise ConversationAccessDenied(
                "Anonymous access is not allowed in strict validation mode."
            )

        config = load_app_config()
        server_config = ServerConfig()
        store_cls: type[ConversationStore] = get_impl(
            ConversationStore, server_config.conversation_store_class
        )
        store = await store_cls.get_instance(config, user_id)

        try:
            metadata = await store.get_metadata(conversation_id)
        except FileNotFoundError:
            # First access — create and assign to this user
            metadata = await self._create_metadata(store, conversation_id, user_id)

        if metadata.user_id is not None and metadata.user_id != user_id:
            raise ConversationAccessDenied(
                f"User {user_id} does not own conversation {conversation_id}."
            )
        return user_id

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _extract_user_id(self, authorization_header: str | None) -> str | None:
        """Derive a user identity from the auth header.

        Override in subclasses for real JWT / OAuth parsing.
        The base implementation returns ``None`` (anonymous).
        """
        return None

    async def _ensure_metadata_exists(
        self, conversation_id: str, user_id: str | None
    ) -> ConversationMetadata:
        config = load_app_config()
        server_config = ServerConfig()
        conversation_store_class: type[ConversationStore] = get_impl(
            ConversationStore,
            server_config.conversation_store_class,
        )
        conversation_store = await conversation_store_class.get_instance(
            config, user_id
        )
        try:
            metadata = await conversation_store.get_metadata(conversation_id)
        except FileNotFoundError:
            logger.info(
                "Creating new conversation metadata for %s",
                conversation_id,
                extra={"session_id": conversation_id},
            )
            metadata = await self._create_metadata(
                conversation_store, conversation_id, user_id
            )
        return metadata

    @staticmethod
    async def _create_metadata(
        store: ConversationStore,
        conversation_id: str,
        user_id: str | None,
    ) -> ConversationMetadata:
        meta = ConversationMetadata(
            conversation_id=conversation_id,
            user_id=user_id,
            title=get_default_conversation_title(conversation_id),
            last_updated_at=datetime.now(UTC),
            selected_repository=None,
        )
        await store.save_metadata(meta)
        return await store.get_metadata(conversation_id)


def create_conversation_validator() -> ConversationValidator:
    """Create conversation validator from environment configuration.

    Returns:
        ConversationValidator instance (default or custom implementation)
    """
    conversation_validator_cls = os.environ.get(
        "APP_CONVERSATION_VALIDATOR_CLS",
        "backend.persistence.conversation.conversation_validator.ConversationValidator",
    )
    ConversationValidatorImpl = get_impl(
        ConversationValidator, conversation_validator_cls
    )
    return ConversationValidatorImpl()
