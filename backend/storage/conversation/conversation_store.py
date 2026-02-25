"""Abstract base interfaces for conversation metadata storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from backend.utils.async_utils import wait_all

if TYPE_CHECKING:
    from collections.abc import Iterable

    from backend.core.config.forge_config import ForgeConfig
    from backend.storage.data_models.conversation_metadata import ConversationMetadata
    from backend.storage.data_models.conversation_metadata_result_set import (
        ConversationMetadataResultSet,
    )


class ConversationStore(ABC):
    """Abstract base class for conversation metadata storage.

    This is an extension point in Forge that allows applications to customize how
    conversation metadata is stored. Applications can substitute their own implementation by:
    1. Creating a class that inherits from ConversationStore
    2. Implementing all required methods
    3. Setting server_config.conversation_store_class to the fully qualified name of the class

    The class is instantiated via get_impl() in forge.server.shared.py.

    The implementation may or may not support multiple users depending on the environment.
    """

    @abstractmethod
    async def save_metadata(self, metadata: ConversationMetadata) -> None:
        """Store conversation metadata."""

    @abstractmethod
    async def get_metadata(self, conversation_id: str) -> ConversationMetadata:
        """Load conversation metadata."""

    async def validate_metadata(self, conversation_id: str, user_id: str) -> bool:
        """Validate that conversation belongs to the current user."""
        metadata = await self.get_metadata(conversation_id)
        return bool(metadata.user_id and metadata.user_id == user_id)

    @abstractmethod
    async def delete_metadata(self, conversation_id: str) -> None:
        """Delete conversation metadata."""

    @abstractmethod
    async def delete_all_metadata(self) -> None:
        """Delete all conversation metadata."""

    @abstractmethod
    async def exists(self, conversation_id: str) -> bool:
        """Check if conversation exists."""

    @abstractmethod
    async def search(
        self, page_id: str | None = None, limit: int = 20
    ) -> ConversationMetadataResultSet:
        """Search conversations."""

    async def get_all_metadata(
        self, conversation_ids: Iterable[str]
    ) -> list[ConversationMetadata]:
        """Get metadata for multiple conversations in parallel."""
        return await wait_all([self.get_metadata(cid) for cid in conversation_ids])

    @classmethod
    @abstractmethod
    async def get_instance(
        cls, config: ForgeConfig, user_id: str | None
    ) -> ConversationStore:
        """Get a store for the user represented by the token given."""
