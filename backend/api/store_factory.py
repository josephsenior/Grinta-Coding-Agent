"""Typed factory functions for store instantiation.

Works around mypy limitation where type[BaseStore].get_instance() isn't
recognized as valid even though get_instance is defined on the base class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config import ForgeConfig
    from backend.storage.conversation.conversation_store import ConversationStore
    from backend.storage.secrets.secrets_store import SecretsStore
    from backend.storage.settings.settings_store import SettingsStore


async def get_conversation_store_instance(
    impl_class: type[ConversationStore],
    config: ForgeConfig,
    user_id: str | None,
) -> ConversationStore:
    """Get a conversation store instance using the implementation class.

    Args:
        impl_class: The conversation store implementation class
        config: Forge configuration
        user_id: User identifier

    Returns:
        Conversation store instance
    """
    return await impl_class.get_instance(config, user_id)


async def get_settings_store_instance(
    impl_class: type[SettingsStore],
    config: ForgeConfig,
    user_id: str | None,
) -> SettingsStore:
    """Get a settings store instance using the implementation class.

    Args:
        impl_class: The settings store implementation class
        config: Forge configuration
        user_id: User identifier

    Returns:
        Settings store instance
    """
    return await impl_class.get_instance(config, user_id)


async def get_secrets_store_instance(
    impl_class: type[SecretsStore],
    config: ForgeConfig,
    user_id: str | None,
) -> SecretsStore:
    """Get a secrets store instance using the implementation class.

    Args:
        impl_class: The secrets store implementation class
        config: Forge configuration
        user_id: User identifier

    Returns:
        Secrets store instance
    """
    return await impl_class.get_instance(config, user_id)
