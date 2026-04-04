"""Unit tests for current storage backend selection helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import backend.persistence.knowledge_base.knowledge_base_store as kb_store_module


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    """Reset the cached global knowledge base store between tests."""
    kb_store_module._store = None
    yield
    kb_store_module._store = None


def test_get_knowledge_base_store_defaults_to_file_backend(monkeypatch) -> None:
    monkeypatch.delenv('APP_KB_STORAGE_TYPE', raising=False)
    monkeypatch.delenv('APP_KB_STORAGE_PATH', raising=False)

    instance = MagicMock()
    with patch.object(kb_store_module, 'KnowledgeBaseStore', return_value=instance) as store:
        result = kb_store_module.get_knowledge_base_store()

    assert result is instance
    store.assert_called_once_with(storage_dir=None)


def test_get_knowledge_base_store_uses_custom_storage_path(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv('APP_KB_STORAGE_TYPE', raising=False)
    monkeypatch.setenv('APP_KB_STORAGE_PATH', str(tmp_path))

    instance = MagicMock()
    with patch.object(kb_store_module, 'KnowledgeBaseStore', return_value=instance) as store:
        result = kb_store_module.get_knowledge_base_store()

    assert result is instance
    store.assert_called_once_with(storage_dir=tmp_path)


def test_get_knowledge_base_store_uses_database_backend(monkeypatch) -> None:
    monkeypatch.setenv('APP_KB_STORAGE_TYPE', 'database')
    db_store = MagicMock()
    adapter = MagicMock()

    with patch(
        'backend.persistence.knowledge_base.database_knowledge_base_store.DatabaseKnowledgeBaseStore',
        return_value=db_store,
    ) as database_store:
        with patch(
            'backend.persistence.knowledge_base.database_store_adapter.DatabaseStoreAdapter',
            return_value=adapter,
        ) as database_adapter:
            result = kb_store_module.get_knowledge_base_store()

    assert result is adapter
    database_store.assert_called_once_with()
    database_adapter.assert_called_once_with(db_store)
