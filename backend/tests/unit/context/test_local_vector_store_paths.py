"""Tests for canonical local vector-store persistence paths."""

from __future__ import annotations

from unittest.mock import patch

from backend.context.vector_store import SQLiteBM25Backend


def test_sqlite_bm25_backend_defaults_to_project_storage_memory_sqlite(
    tmp_path,
) -> None:
    with patch(
        'backend.context.vector_store._local_vector_store.get_active_local_data_root',
        return_value=str(tmp_path / '.grinta' / 'storage'),
    ):
        backend = SQLiteBM25Backend()

    assert (
        backend.db_path
        == tmp_path / '.grinta' / 'storage' / 'memory' / 'sqlite' / 'APP_memory_fts.db'
    )
    assert backend.db_path.exists()
