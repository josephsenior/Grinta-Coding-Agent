"""Filesystem-backed implementation of the conversation metadata store."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from backend.core.logger import app_logger as logger
from backend.persistence import get_file_store
from backend.persistence.conversation.conversation_store import ConversationStore
from backend.persistence.data_models.conversation_metadata import ConversationMetadata
from backend.persistence.data_models.conversation_metadata_result_set import (
    ConversationMetadataResultSet,
)
from backend.persistence.locations import (
    CONVERSATION_BASE_DIR,
    get_conversation_dir,
    get_local_data_root,
    get_conversation_metadata_filename,
)
from backend.utils.async_utils import call_sync_from_async
from backend.utils.search_utils import offset_to_page_id, page_id_to_offset

if TYPE_CHECKING:
    from backend.core.config.app_config import AppConfig
    from backend.persistence.files import FileStore

conversation_metadata_type_adapter = TypeAdapter(ConversationMetadata)


class FileConversationStore(ConversationStore):
    """ConversationStore implementation persisting metadata to local filesystem."""

    def __init__(
        self,
        file_store: FileStore,
        config: AppConfig | None | None = None,
        user_id: str | None = None,
    ) -> None:
        """Capture configuration, file store, and ensure local directories exist."""
        if config is None:
            from backend.core.config.app_config import AppConfig

            config = AppConfig()
        self.config = config
        self.file_store = file_store
        self.user_id = user_id

        base_path = Path(os.path.expanduser(get_local_data_root(self.config))) / Path(
            self.get_conversation_metadata_dir()
        )
        base_path.mkdir(parents=True, exist_ok=True)
        self._local_conversations_dir = base_path

    async def save_metadata(self, metadata: ConversationMetadata) -> None:
        """Save conversation metadata to storage.

        Args:
            metadata: Conversation metadata to save

        """
        json_str = conversation_metadata_type_adapter.dump_json(metadata)
        path = self.get_conversation_metadata_filename(metadata.conversation_id)
        try:
            await call_sync_from_async(self.file_store.write, path, json_str)
        except OSError as e:
            logger.warning(
                'Could not save conversation metadata for %s: %s',
                metadata.conversation_id,
                e,
                extra={'conversation_id': metadata.conversation_id},
            )

    async def get_metadata(
        self,
        conversation_id: str,
        *,
        create_if_missing: bool = True,
    ) -> ConversationMetadata:
        """Get conversation metadata by ID.

        Creates new metadata if file is corrupt or missing.

        Args:
            conversation_id: Conversation ID
            create_if_missing: If True, create default metadata when the file is
                missing or corrupt. Defaults to True.

        Returns:
            Conversation metadata object

        """
        path = self.get_conversation_metadata_filename(conversation_id)
        try:
            json_str = await call_sync_from_async(self.file_store.read, path)
            if not json_str or json_str.strip() == '':
                raise FileNotFoundError(f'Empty conversation metadata file: {path}')
            json_obj = json.loads(json_str)
            if 'created_at' not in json_obj:
                raise FileNotFoundError(f'Invalid conversation metadata file: {path}')
            if 'github_user_id' in json_obj:
                json_obj.pop('github_user_id')
            return conversation_metadata_type_adapter.validate_python(json_obj)
        except (json.JSONDecodeError, FileNotFoundError):
            if not create_if_missing:
                raise
            # If metadata is corrupted or missing, create a new one
            from datetime import datetime

            metadata = ConversationMetadata(
                conversation_id=conversation_id,
                selected_repository=None,
                created_at=datetime.now(),
                title='New Conversation',
                user_id='dev-user',
            )
            await self.save_metadata(metadata)
            return metadata

    async def delete_metadata(self, conversation_id: str) -> None:
        """Delete conversation metadata and associated files.

        Args:
            conversation_id: Conversation ID to delete

        """
        conversation_dir = get_conversation_dir(conversation_id, self.user_id)
        await call_sync_from_async(self.file_store.delete, conversation_dir)

    async def delete_all_metadata(self) -> None:
        """Delete all conversation metadata and associated files."""
        metadata_dir = self.get_conversation_metadata_dir()
        try:
            conversation_ids = [
                Path(path).name
                for path in self.file_store.list(metadata_dir)
                if not Path(path).name.startswith('.')
            ]
        except FileNotFoundError:
            return

        for conversation_id in conversation_ids:
            await self.delete_metadata(conversation_id)

    async def exists(self, conversation_id: str) -> bool:
        """Check if conversation metadata exists.

        Args:
            conversation_id: Conversation ID to check

        Returns:
            True if conversation exists

        """
        path = self.get_conversation_metadata_filename(conversation_id)
        try:
            await call_sync_from_async(self.file_store.read, path)
            return True
        except FileNotFoundError:
            return False

    async def search(
        self, page_id: str | None = None, limit: int = 20
    ) -> ConversationMetadataResultSet:
        """Search conversations with pagination.

        Args:
            page_id: Optional page ID for pagination
            limit: Maximum results per page

        Returns:
            Result set with conversations and next page ID

        """
        conversations: list[ConversationMetadata] = []
        metadata_dir = self.get_conversation_metadata_dir()
        try:
            conversation_ids = [
                Path(path).name
                for path in self.file_store.list(metadata_dir)
                if not Path(path).name.startswith('.')
            ]
        except FileNotFoundError:
            return ConversationMetadataResultSet([])
        num_conversations = len(conversation_ids)
        start = page_id_to_offset(page_id)
        end = min(limit + start, num_conversations)
        conversations = []
        for conversation_id in conversation_ids:
            try:
                conversations.append(
                    await self.get_metadata(
                        conversation_id,
                        create_if_missing=False,
                    )
                )
            except Exception:
                logger.warning(
                    'Could not load conversation metadata: %s', conversation_id
                )
        conversations.sort(key=_sort_key, reverse=True)
        conversations = conversations[start:end]
        next_page_id = offset_to_page_id(end, end < num_conversations)
        return ConversationMetadataResultSet(conversations, next_page_id)

    def get_conversation_metadata_dir(self) -> str:
        """Get base directory for conversation metadata.

        Returns:
            Base directory path

        """
        if self.user_id:
            return f'users/{self.user_id}/conversations'
        return CONVERSATION_BASE_DIR

    def get_conversation_metadata_filename(self, conversation_id: str) -> str:
        """Get metadata filename for conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            Full path to metadata file

        """
        return get_conversation_metadata_filename(conversation_id, self.user_id)

    @classmethod
    async def get_instance(
        cls, config: AppConfig, user_id: str | None
    ) -> FileConversationStore:
        """Get FileConversationStore singleton instance.

        Args:
            config: Application configuration
            user_id: Optional user ID for scoping

        Returns:
            FileConversationStore instance

        """
        file_store = get_file_store(
            file_store_type=config.file_store,
            local_data_root=config.local_data_root,
            file_store_web_hook_url=config.file_store_web_hook_url,
            file_store_web_hook_headers=config.file_store_web_hook_headers,
            file_store_web_hook_batch=config.file_store_web_hook_batch,
        )
        return cls(file_store, config=config, user_id=user_id)


def _sort_key(conversation: ConversationMetadata) -> str:
    if created_at := conversation.created_at:
        return created_at.isoformat()
    return ''
