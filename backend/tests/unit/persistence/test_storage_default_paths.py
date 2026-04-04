"""Tests for canonical conversation persistence roots."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.core.config.app_config import AppConfig
from backend.persistence.conversation.file_conversation_store import (
    FileConversationStore,
)
from backend.persistence.knowledge_base.knowledge_base_store import KnowledgeBaseStore


def test_file_conversation_store_uses_configured_local_data_root(tmp_path) -> None:
    file_store = MagicMock()
    data_root = tmp_path / '.grinta' / 'storage'
    config = AppConfig(local_data_root=str(data_root), project_root=None)

    store = FileConversationStore(file_store=file_store, config=config, user_id=None)

    assert store._local_conversations_dir == data_root / 'sessions'
    assert store._local_conversations_dir.exists()


def test_file_conversation_store_uses_app_dir_under_project_root(tmp_path) -> None:
    file_store = MagicMock()
    workspace = tmp_path / 'workspace'
    config = AppConfig(
        project_root=str(workspace),
        local_data_root=str(workspace / '.grinta' / 'storage'),
    )

    store = FileConversationStore(file_store=file_store, config=config, user_id='u1')

    assert store._local_conversations_dir == workspace / '.grinta' / 'storage' / 'users' / 'u1' / 'conversations'
    assert store._local_conversations_dir.exists()


def test_knowledge_base_store_defaults_to_home_app_kb(tmp_path) -> None:
    with patch(
        'backend.persistence.knowledge_base.knowledge_base_store.get_active_local_data_root',
        return_value=str(tmp_path / '.grinta' / 'storage'),
    ):
        store = KnowledgeBaseStore(storage_dir=None)

    assert store.storage_dir == tmp_path / '.grinta' / 'storage' / 'kb'
    assert store.storage_dir.exists()


def test_knowledge_base_store_keeps_explicit_storage_dir(tmp_path) -> None:
    storage_dir = tmp_path / 'custom-kb'

    store = KnowledgeBaseStore(storage_dir=storage_dir)

    assert store.storage_dir == storage_dir
    assert store.storage_dir.exists()
