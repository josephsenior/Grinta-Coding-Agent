from __future__ import annotations

from pathlib import Path

from backend.persistence.data_models.knowledge_base import KnowledgeBaseDocument
from backend.persistence.knowledge_base.knowledge_base_store import (
    KnowledgeBaseStore,
    get_knowledge_base_store,
)


def _doc(collection_id: str, *, filename: str = 'a.txt', size: int = 10, h: str = 'h1'):
    return KnowledgeBaseDocument(
        collection_id=collection_id,
        filename=filename,
        content_hash=h,
        file_size_bytes=size,
        mime_type='text/plain',
    )


def test_collection_crud_and_document_lifecycle(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(storage_dir=tmp_path)
    col = store.create_collection('u1', 'Docs', 'desc')
    assert store.get_collection(col.id) is not None
    assert len(store.list_collections('u1')) == 1

    updated = store.update_collection(col.id, name='Docs2', description='desc2')
    assert updated is not None
    assert updated.name == 'Docs2'

    d1 = store.add_document(_doc(col.id, filename='f1.txt', size=11, h='hx'))
    d2 = store.add_document(_doc(col.id, filename='f2.txt', size=12, h='hy'))
    assert store.get_document(d1.id) is not None
    assert len(store.list_documents(col.id)) == 2
    assert store.get_document_by_hash('hx') is not None
    assert store.get_document_by_hash('missing') is None

    stats = store.get_stats()
    assert stats['total_collections'] == 1
    assert stats['total_documents'] == 2
    assert stats['total_size_bytes'] == 23

    assert store.delete_document(d1.id) is True
    assert store.delete_document('no-such-doc') is False
    assert len(store.list_documents(col.id)) == 1

    assert store.delete_collection(col.id) is True
    assert store.delete_collection(col.id) is False


def test_store_loads_data_from_disk(tmp_path: Path) -> None:
    store1 = KnowledgeBaseStore(storage_dir=tmp_path)
    col = store1.create_collection('u2', 'Persisted')
    d = store1.add_document(_doc(col.id, filename='persist.txt', size=7, h='p1'))

    store2 = KnowledgeBaseStore(storage_dir=tmp_path)
    loaded_col = store2.get_collection(col.id)
    loaded_doc = store2.get_document(d.id)

    assert loaded_col is not None
    assert loaded_col.name == 'Persisted'
    assert loaded_doc is not None
    assert loaded_doc.filename == 'persist.txt'


def test_delete_document_handles_missing_id_in_collection_list(tmp_path: Path) -> None:
    store = KnowledgeBaseStore(storage_dir=tmp_path)
    col = store.create_collection('u3', 'Corrupt')
    d = store.add_document(_doc(col.id, filename='a.txt', size=5, h='hh'))

    # Simulate corrupted state: doc present in map, but absent from collection list.
    store._collection_documents[col.id] = []
    assert store.delete_document(d.id) is True


def test_get_knowledge_base_store_uses_env_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('APP_KB_STORAGE_PATH', str(tmp_path))
    import backend.persistence.knowledge_base.knowledge_base_store as mod

    old = mod._store
    try:
        mod._store = None
        s = get_knowledge_base_store()
        assert isinstance(s, KnowledgeBaseStore)
        assert Path(s.storage_dir).resolve() == tmp_path.resolve()
    finally:
        mod._store = old
