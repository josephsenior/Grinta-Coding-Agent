"""Tests for default persistence roots that still live outside the workspace tree."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.core.config.app_config import AppConfig
from backend.persistence.conversation.file_conversation_store import (
    FileConversationStore,
)
from backend.persistence.knowledge_base.knowledge_base_store import KnowledgeBaseStore


def test_file_conversation_store_uses_app_dir_under_settings_root(tmp_path) -> None:
    file_store = MagicMock()
    config = AppConfig(project_root=None)

    with patch(
        "backend.core.app_paths.get_app_settings_root",
        return_value=str(tmp_path),
    ):
        store = FileConversationStore(file_store=file_store, config=config, user_id=None)

    assert store._local_conversations_dir == tmp_path / ".app" / "conversations"
    assert store._local_conversations_dir.exists()


def test_file_conversation_store_uses_app_dir_under_project_root(tmp_path) -> None:
    file_store = MagicMock()
    workspace = tmp_path / "workspace"
    config = AppConfig(project_root=str(workspace))

    store = FileConversationStore(file_store=file_store, config=config, user_id="u1")

    assert store._local_conversations_dir == workspace / ".app" / "conversations" / "u1"
    assert store._local_conversations_dir.exists()


def test_knowledge_base_store_defaults_to_home_app_kb(tmp_path) -> None:
    with patch("backend.persistence.knowledge_base.knowledge_base_store.Path.home", return_value=tmp_path):
        store = KnowledgeBaseStore(storage_dir=None)

    assert store.storage_dir == tmp_path / ".app" / "kb"
    assert store.storage_dir.exists()


def test_knowledge_base_store_keeps_explicit_storage_dir(tmp_path) -> None:
    storage_dir = tmp_path / "custom-kb"

    store = KnowledgeBaseStore(storage_dir=storage_dir)

    assert store.storage_dir == storage_dir
    assert store.storage_dir.exists()