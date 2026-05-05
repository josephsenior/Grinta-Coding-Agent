"""Tests for canonical local vector-store persistence paths."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

from backend.context.local_vector_store import ChromaDBBackend, SQLiteBM25Backend


def test_chromadb_backend_defaults_to_project_storage_memory_chroma(tmp_path) -> None:
    fake_client = MagicMock()
    fake_collection = MagicMock()
    fake_collection.count.return_value = 0
    fake_client.get_collection.side_effect = Exception('missing')
    fake_client.create_collection.return_value = fake_collection
    fake_ef_module = types.SimpleNamespace(
        DefaultEmbeddingFunction=MagicMock(return_value=MagicMock()),
        FastEmbedEmbeddingFunction=MagicMock(return_value=MagicMock()),
    )

    fake_chromadb = types.ModuleType('chromadb')
    fake_chromadb.PersistentClient = MagicMock(return_value=fake_client)
    fake_chromadb_config = types.ModuleType('chromadb.config')
    fake_chromadb_config.Settings = lambda **kwargs: kwargs
    fake_chromadb_utils = types.ModuleType('chromadb.utils')
    fake_chromadb_utils.embedding_functions = fake_ef_module

    with (
        patch.dict(
            sys.modules,
            {
                'chromadb': fake_chromadb,
                'chromadb.config': fake_chromadb_config,
                'chromadb.utils': fake_chromadb_utils,
            },
        ),
        patch(
            'backend.context.local_vector_store.get_active_local_data_root',
            return_value=str(tmp_path / '.grinta' / 'storage'),
        ),
    ):
        backend = ChromaDBBackend(warm_model_in_background=False)

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
