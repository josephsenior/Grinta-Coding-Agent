"""Tests for canonical local vector-store persistence paths."""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

from backend.context.local_vector_store import ChromaDBBackend, SQLiteBM25Backend


def test_chromadb_backend_defaults_to_project_storage_memory_chroma(tmp_path) -> None:
    fake_client = MagicMock()
    fake_collection = MagicMock()
    fake_collection.count.return_value = 0
    fake_client.get_collection.side_effect = Exception('missing')
    fake_client.create_collection.return_value = fake_collection
    fake_model = MagicMock()
    fake_sentence_transformers = types.SimpleNamespace(
        SentenceTransformer=MagicMock(return_value=fake_model)
    )

    with (
        patch(
            'backend.context.local_vector_store.get_active_local_data_root',
            return_value=str(tmp_path / '.grinta' / 'storage'),
        ),
        patch(
            'chromadb.PersistentClient',
            return_value=fake_client,
        ),
        patch(
            'chromadb.config.Settings',
            side_effect=lambda **kwargs: kwargs,
        ),
        patch.dict(
            'sys.modules',
            {'sentence_transformers': fake_sentence_transformers},
        ),
    ):
        backend = ChromaDBBackend()

    assert backend.client is fake_client
    assert (tmp_path / '.grinta' / 'storage' / 'memory' / 'chroma').exists()


def test_sqlite_bm25_backend_defaults_to_project_storage_memory_sqlite(
    tmp_path,
) -> None:
    with patch(
        'backend.context.local_vector_store.get_active_local_data_root',
        return_value=str(tmp_path / '.grinta' / 'storage'),
    ):
        backend = SQLiteBM25Backend()

    assert (
        backend.db_path
        == tmp_path / '.grinta' / 'storage' / 'memory' / 'sqlite' / 'APP_memory_fts.db'
    )
    assert backend.db_path.exists()
