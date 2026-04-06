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
    monkeypatch.delenv('APP_KB_STORAGE_PATH', raising=False)

    instance = MagicMock()
    with patch.object(kb_store_module, 'KnowledgeBaseStore', return_value=instance) as store:
        result = kb_store_module.get_knowledge_base_store()

    assert result is instance
    store.assert_called_once_with(storage_dir=None)


def test_get_knowledge_base_store_uses_custom_storage_path(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('APP_KB_STORAGE_PATH', str(tmp_path))

    instance = MagicMock()
    with patch.object(kb_store_module, 'KnowledgeBaseStore', return_value=instance) as store:
        result = kb_store_module.get_knowledge_base_store()

    assert result is instance
    store.assert_called_once_with(storage_dir=tmp_path)
