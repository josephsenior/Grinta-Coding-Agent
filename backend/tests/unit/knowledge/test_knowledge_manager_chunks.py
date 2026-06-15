"""Additional KnowledgeBaseManager coverage for chunk and search paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.knowledge.knowledge_base_manager import KnowledgeBaseManager
from backend.persistence.data_models.knowledge_base import (
    DocumentChunk,
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
)


@patch('backend.knowledge.knowledge_base_manager.get_knowledge_base_store')
@patch('backend.knowledge.knowledge_base_manager.EnhancedVectorStore')
def test_add_chunks_to_vector_store_batch_success(
    mock_vector_store_cls, mock_get_store
) -> None:
    mock_get_store.return_value = MagicMock()
    vector_store = MagicMock()
    mock_vector_store_cls.return_value = vector_store
    manager = KnowledgeBaseManager(user_id='user123')
    document = KnowledgeBaseDocument(
        collection_id='col1',
        filename='readme.md',
        content_hash='hash',
        file_size_bytes=10,
        mime_type='text/plain',
    )
    chunks = [
        DocumentChunk(
            id='c1',
            document_id='doc1',
            chunk_index=0,
            content='hello',
            metadata={'section': 'intro'},
        )
    ]
    added = manager._add_chunks_to_vector_store('col1', chunks, document, 'readme.md')
    assert added == 1
    vector_store.add_batch.assert_called_once()


@patch('backend.knowledge.knowledge_base_manager.get_knowledge_base_store')
@patch('backend.knowledge.knowledge_base_manager.EnhancedVectorStore')
def test_add_chunks_to_vector_store_handles_batch_failure(
    mock_vector_store_cls, mock_get_store
) -> None:
    mock_get_store.return_value = MagicMock()
    vector_store = MagicMock()
    vector_store.add_batch.side_effect = RuntimeError('vector down')
    mock_vector_store_cls.return_value = vector_store
    manager = KnowledgeBaseManager(user_id='user123')
    document = KnowledgeBaseDocument(
        collection_id='col1',
        filename='readme.md',
        content_hash='hash',
        file_size_bytes=10,
        mime_type='text/plain',
    )
    chunks = [
        DocumentChunk(
            id='c1',
            document_id='doc1',
            chunk_index=0,
            content='hello',
        )
    ]
    assert manager._add_chunks_to_vector_store('col1', chunks, document, 'readme.md') == 0


@patch('backend.knowledge.knowledge_base_manager.get_knowledge_base_store')
@patch('backend.knowledge.knowledge_base_manager.EnhancedVectorStore')
def test_search_skips_invalid_score_types(mock_vector_store_cls, mock_get_store) -> None:
    mock_store = MagicMock()
    mock_store.get_collection.return_value = KnowledgeBaseCollection(
        id='col1', user_id='user123', name='Test'
    )
    mock_get_store.return_value = mock_store
    vector_store = MagicMock()
    vector_store.search.return_value = [
        {
            'score': 'bad',
            'document_id': 'd1',
            'collection_id': 'col1',
            'filename': 'a.md',
            'excerpt': 'text',
        },
        {
            'score': True,
            'document_id': 'd2',
            'collection_id': 'col1',
            'filename': 'b.md',
            'excerpt': 'text',
        },
    ]
    mock_vector_store_cls.return_value = vector_store
    manager = KnowledgeBaseManager(user_id='user123')
    assert manager.search('query', collection_ids=['col1'], relevance_threshold=0.1) == []


@patch('backend.knowledge.knowledge_base_manager.get_knowledge_base_store')
def test_search_without_accessible_collections_returns_empty(mock_get_store) -> None:
    mock_store = MagicMock()
    mock_store.get_collection.return_value = None
    mock_get_store.return_value = mock_store
    manager = KnowledgeBaseManager(user_id='user123')
    assert manager.search('query', collection_ids=['missing']) == []
