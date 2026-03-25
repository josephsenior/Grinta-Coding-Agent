"""Tests for backend.knowledge_base.knowledge_base_manager — knowledge base manager."""

from unittest.mock import MagicMock, patch


from backend.knowledge_base.knowledge_base_manager import KnowledgeBaseManager
from backend.storage.data_models.knowledge_base import (
    DocumentChunk,
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
    KnowledgeBaseSearchResult,
)


class TestKnowledgeBaseManagerInit:
    """Tests for KnowledgeBaseManager initialization."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_create_manager(self, mock_get_store):
        """Test creating KnowledgeBaseManager."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")

        assert manager.user_id == "user123"
        assert manager.store == mock_store
        assert manager._vector_stores == {}

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_manager_multiple_users(self, mock_get_store):
        """Test creating managers for different users."""
        mock_get_store.return_value = MagicMock()

        manager1 = KnowledgeBaseManager(user_id="user1")
        manager2 = KnowledgeBaseManager(user_id="user2")

        assert manager1.user_id == "user1"
        assert manager2.user_id == "user2"
        assert manager1 is not manager2


class TestGetVectorStore:
    """Tests for _get_vector_store method."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_creates_vector_store_first_time(
        self, mock_vector_store_cls, mock_get_store
    ):
        """Test vector store is created on first access."""
        mock_get_store.return_value = MagicMock()
        mock_vector_store = MagicMock()
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager._get_vector_store("col123")

        mock_vector_store_cls.assert_called_once_with(
            collection_name="kb_col123",
            enable_cache=True,
            enable_reranking=True,
        )
        assert result == mock_vector_store
        assert manager._vector_stores["col123"] == mock_vector_store

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_reuses_vector_store(self, mock_vector_store_cls, mock_get_store):
        """Test vector store is reused on subsequent access."""
        mock_get_store.return_value = MagicMock()
        mock_vector_store = MagicMock()
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result1 = manager._get_vector_store("col123")
        result2 = manager._get_vector_store("col123")

        assert mock_vector_store_cls.call_count == 1
        assert result1 == result2


class TestCollectionOperations:
    """Tests for collection CRUD operations."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_create_collection(self, mock_get_store):
        """Test creating a collection."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            user_id="user123", name="My Collection"
        )
        mock_store.create_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.create_collection(name="My Collection", description="Test")

        mock_store.create_collection.assert_called_once_with(
            user_id="user123",
            name="My Collection",
            description="Test",
        )
        assert result == mock_collection

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_collection_success(self, mock_get_store):
        """Test getting a collection that exists and user has access."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.get_collection("col123")

        assert result == mock_collection

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_collection_access_denied(self, mock_get_store):
        """Test getting a collection for different user returns None."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="other_user", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.get_collection("col123")

        assert result is None

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_collection_not_found(self, mock_get_store):
        """Test getting a collection that doesn't exist."""
        mock_store = MagicMock()
        mock_store.get_collection.return_value = None
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.get_collection("col123")

        assert result is None

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_list_collections(self, mock_get_store):
        """Test listing collections for user."""
        mock_store = MagicMock()
        mock_collections = [
            KnowledgeBaseCollection(user_id="user123", name="Col1"),
            KnowledgeBaseCollection(user_id="user123", name="Col2"),
        ]
        mock_store.list_collections.return_value = mock_collections
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.list_collections()

        mock_store.list_collections.assert_called_once_with("user123")
        assert result == mock_collections

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_update_collection_success(self, mock_get_store):
        """Test updating a collection."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Old Name"
        )
        updated_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="New Name"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.update_collection.return_value = updated_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.update_collection("col123", name="New Name")

        mock_store.update_collection.assert_called_once_with("col123", "New Name", None)
        assert result == updated_collection

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_update_collection_access_denied(self, mock_get_store):
        """Test updating collection for different user returns None."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="other_user", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.update_collection("col123", name="New Name")

        assert result is None
        mock_store.update_collection.assert_not_called()

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_delete_collection_success(self, mock_vector_store_cls, mock_get_store):
        """Test deleting a collection."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.list_documents.return_value = []
        mock_store.delete_collection.return_value = True
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.delete_by_metadata.return_value = 5
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.delete_collection("col123")

        assert result is True
        mock_store.delete_collection.assert_called_once_with("col123")
        mock_vector_store.delete_by_metadata.assert_called_once()

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_delete_collection_access_denied(self, mock_get_store):
        """Test deleting collection for different user."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="other_user", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.delete_collection("col123")

        assert result is False
        mock_store.delete_collection.assert_not_called()


class TestChunkContent:
    """Tests for _chunk_content method."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_chunk_short_content(self, mock_get_store):
        """Test chunking content shorter than chunk size."""
        mock_get_store.return_value = MagicMock()
        manager = KnowledgeBaseManager(user_id="user123")

        content = "Short content"
        chunks = manager._chunk_content(content, "doc123")

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].document_id == "doc123"
        assert chunks[0].chunk_index == 0

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_chunk_long_content(self, mock_get_store):
        """Test chunking content longer than chunk size."""
        mock_get_store.return_value = MagicMock()
        manager = KnowledgeBaseManager(user_id="user123")

        content = "a" * 5000  # Exceeds default chunk_size (4000)
        chunks = manager._chunk_content(content, "doc123")

        assert len(chunks) > 1
        assert all(chunk.document_id == "doc123" for chunk in chunks)
        assert all(isinstance(chunk, DocumentChunk) for chunk in chunks)

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_chunk_with_metadata(self, mock_get_store):
        """Test chunking content with metadata."""
        mock_get_store.return_value = MagicMock()
        manager = KnowledgeBaseManager(user_id="user123")

        content = "Content with metadata"
        metadata = {"key": "value"}
        chunks = manager._chunk_content(content, "doc123", metadata)

        assert chunks[0].metadata == metadata

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_chunk_preserves_order(self, mock_get_store):
        """Test chunks have increasing indices."""
        mock_get_store.return_value = MagicMock()
        manager = KnowledgeBaseManager(user_id="user123")

        content = "a" * 5000  # Exceeds default chunk_size (4000)
        chunks = manager._chunk_content(content, "doc123")

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i


class TestAddDocument:
    """Tests for add_document method."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_add_document_success(self, mock_vector_store_cls, mock_get_store):
        """Test adding a document successfully."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.get_document_by_hash.return_value = None

        mock_doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_store.add_document.return_value = mock_doc
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.add_document(
            collection_id="col123",
            filename="test.txt",
            content="Test content",
            mime_type="text/plain",
        )

        assert result is not None
        assert isinstance(result, KnowledgeBaseDocument)
        mock_store.add_document.assert_called_once()

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_add_document_collection_not_found(self, mock_get_store):
        """Test adding document to non-existent collection."""
        mock_store = MagicMock()
        mock_store.get_collection.return_value = None
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.add_document(
            collection_id="col123",
            filename="test.txt",
            content="Test content",
        )

        assert result is None
        mock_store.add_document.assert_not_called()

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_add_document_duplicate(self, mock_get_store):
        """Test adding duplicate document returns existing."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        existing_doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="existing.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.get_document_by_hash.return_value = existing_doc
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.add_document(
            collection_id="col123",
            filename="test.txt",
            content="Test content",
        )

        assert result == existing_doc
        mock_store.add_document.assert_not_called()


class TestDocumentOperations:
    """Tests for document operations."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_document_success(self, mock_get_store):
        """Test getting a document with access."""
        mock_store = MagicMock()
        mock_doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_document.return_value = mock_doc
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.get_document("doc123")

        assert result == mock_doc

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_document_access_denied(self, mock_get_store):
        """Test getting document from collection user doesn't own."""
        mock_store = MagicMock()
        mock_doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="other_user", name="Test"
        )
        mock_store.get_document.return_value = mock_doc
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.get_document("doc123")

        assert result is None

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_list_documents_success(self, mock_get_store):
        """Test listing documents in collection."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_docs = [
            KnowledgeBaseDocument(
                collection_id="col123",
                filename="doc1.txt",
                content_hash="hash1",
                file_size_bytes=100,
                mime_type="text/plain",
            ),
            KnowledgeBaseDocument(
                collection_id="col123",
                filename="doc2.txt",
                content_hash="hash2",
                file_size_bytes=200,
                mime_type="text/plain",
            ),
        ]
        mock_store.get_collection.return_value = mock_collection
        mock_store.list_documents.return_value = mock_docs
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.list_documents("col123")

        assert result == mock_docs

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_list_documents_access_denied(self, mock_get_store):
        """Test listing documents from collection user doesn't own."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="other_user", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.list_documents("col123")

        assert result == []
        mock_store.list_documents.assert_not_called()

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_delete_document_success(self, mock_vector_store_cls, mock_get_store):
        """Test deleting a document."""
        mock_store = MagicMock()
        mock_doc = KnowledgeBaseDocument(
            id="doc123",
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_document.return_value = mock_doc
        mock_store.get_collection.return_value = mock_collection
        mock_store.delete_document.return_value = True
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.delete_by_metadata.return_value = 3
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.delete_document("doc123")

        assert result is True
        mock_store.delete_document.assert_called_once_with("doc123")
        mock_vector_store.delete_by_metadata.assert_called_once()

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_delete_document_not_found(self, mock_get_store):
        """Test deleting non-existent document."""
        mock_store = MagicMock()
        mock_store.get_document.return_value = None
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.delete_document("doc123")

        assert result is False
        mock_store.delete_document.assert_not_called()


class TestSearch:
    """Tests for search operations."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_search_single_collection(self, mock_vector_store_cls, mock_get_store):
        """Test searching in single collection."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = [
            {
                "content": "Test content",
                "score": 0.9,
                "metadata": {
                    "document_id": "doc123",
                    "collection_id": "col123",
                    "filename": "test.txt",
                },
            }
        ]
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        results = manager.search("test query", collection_ids=["col123"])

        assert len(results) == 1
        assert isinstance(results[0], KnowledgeBaseSearchResult)
        assert results[0].relevance_score == 0.9

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_search_filters_by_relevance(self, mock_get_store):
        """Test search filters results by relevance threshold."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        # Mock _get_vector_store to return a mock
        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = [
            {
                "content": "Low score",
                "score": 0.3,
                "metadata": {
                    "document_id": "doc1",
                    "collection_id": "col123",
                    "filename": "low.txt",
                },
            },
            {
                "content": "High score",
                "score": 0.9,
                "metadata": {
                    "document_id": "doc2",
                    "collection_id": "col123",
                    "filename": "high.txt",
                },
            },
        ]
        manager._vector_stores["col123"] = mock_vector_store

        results = manager.search(
            "test query", collection_ids=["col123"], relevance_threshold=0.7
        )

        # Only high score result should pass threshold
        assert len(results) == 1
        assert results[0].relevance_score == 0.9

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_search_all_collections(self, mock_get_store):
        """Test searching across all user collections."""
        mock_store = MagicMock()
        mock_collections = [
            KnowledgeBaseCollection(id="col1", user_id="user123", name="Col1"),
            KnowledgeBaseCollection(id="col2", user_id="user123", name="Col2"),
        ]
        mock_store.list_collections.return_value = mock_collections
        mock_store.get_collection.side_effect = mock_collections
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        # Mock vector stores
        for col_id in ["col1", "col2"]:
            mock_vs = MagicMock()
            mock_vs.search.return_value = []
            manager._vector_stores[col_id] = mock_vs

        manager.search("test query", collection_ids=None)

        # Should search both collections
        assert mock_store.list_collections.called


class TestGetStats:
    """Tests for get_stats method."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_stats_empty(self, mock_get_store):
        """Test getting stats with no collections."""
        mock_store = MagicMock()
        mock_store.list_collections.return_value = []
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        stats = manager.get_stats()

        assert stats["total_collections"] == 0
        assert stats["total_documents"] == 0
        assert stats["total_size_bytes"] == 0

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_get_stats_with_collections(self, mock_get_store):
        """Test getting stats with collections."""
        mock_store = MagicMock()
        mock_collections = [
            KnowledgeBaseCollection(
                id="col1",
                user_id="user123",
                name="Col1",
                document_count=5,
                total_size_bytes=1024 * 1024,
            ),
            KnowledgeBaseCollection(
                id="col2",
                user_id="user123",
                name="Col2",
                document_count=3,
                total_size_bytes=2 * 1024 * 1024,
            ),
        ]
        mock_store.list_collections.return_value = mock_collections
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        stats = manager.get_stats()

        assert stats["total_collections"] == 2
        assert stats["total_documents"] == 8
        assert stats["total_size_mb"] == 3.0
        assert len(stats["collections"]) == 2


class TestAdditionalCoveragePaths:
    """Additional tests to cover error paths and edge cases."""

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_add_chunk_to_vector_store_success(
        self, mock_vector_store_cls, mock_get_store
    ):
        """Test _add_chunk_to_vector_store success case."""
        mock_get_store.return_value = MagicMock()
        mock_vector_store = MagicMock()
        mock_vector_store.add.return_value = None
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        chunk = DocumentChunk(document_id="doc123", chunk_index=0, content="Test")
        doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )

        result = manager._add_chunk_to_vector_store(
            mock_vector_store, chunk, doc, "col123", "test.txt"
        )
        assert result is True

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_add_chunk_to_vector_store_error(
        self, mock_vector_store_cls, mock_get_store
    ):
        """Test _add_chunk_to_vector_store error case."""
        mock_get_store.return_value = MagicMock()
        mock_vector_store = MagicMock()
        mock_vector_store.add.side_effect = RuntimeError("Error")
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        chunk = DocumentChunk(document_id="doc123", chunk_index=0, content="Test")
        doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )

        result = manager._add_chunk_to_vector_store(
            mock_vector_store, chunk, doc, "col123", "test.txt"
        )
        assert result is False

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_add_chunks_partial_failure(self, mock_vector_store_cls, mock_get_store):
        """Test _add_chunks_to_vector_store with some failures."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.add.side_effect = [None, RuntimeError("Error"), None]
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        chunks = [
            DocumentChunk(document_id="doc123", chunk_index=i, content=f"Content {i}")
            for i in range(3)
        ]
        doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=300,
            mime_type="text/plain",
        )

        count = manager._add_chunks_to_vector_store("col123", chunks, doc, "test.txt")
        assert count == 2

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_add_chunks_all_fail(self, mock_vector_store_cls, mock_get_store):
        """Test _add_chunks_to_vector_store when all fail."""
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.add.side_effect = RuntimeError("Error")
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        chunks = [DocumentChunk(document_id="doc123", chunk_index=0, content="Content")]
        doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )

        count = manager._add_chunks_to_vector_store("col123", chunks, doc, "test.txt")
        assert count == 0

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_chunk_empty_content(self, mock_get_store):
        """Test chunking empty content."""
        mock_get_store.return_value = MagicMock()
        manager = KnowledgeBaseManager(user_id="user123")
        chunks = manager._chunk_content("", "doc123")
        assert not chunks

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_chunk_whitespace_only(self, mock_get_store):
        """Test chunking whitespace-only content."""
        mock_get_store.return_value = MagicMock()
        manager = KnowledgeBaseManager(user_id="user123")
        chunks = manager._chunk_content("   \n\n\t  ", "doc123")
        assert not chunks

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_delete_collection_vector_error(
        self, mock_vector_store_cls, mock_get_store
    ):
        """Test delete_collection with vector store error."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.list_documents.return_value = []
        mock_store.delete_collection.return_value = True
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.delete_by_metadata.side_effect = RuntimeError("Error")
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.delete_collection("col123")
        assert result is True

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_delete_document_vector_error(self, mock_vector_store_cls, mock_get_store):
        """Test delete_document with vector store error."""
        mock_store = MagicMock()
        mock_doc = KnowledgeBaseDocument(
            id="doc123",
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_document.return_value = mock_doc
        mock_store.get_collection.return_value = mock_collection
        mock_store.delete_document.return_value = True
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.delete_by_metadata.side_effect = RuntimeError("Error")
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        result = manager.delete_document("doc123")
        assert result is True

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_search_error_handling(self, mock_vector_store_cls, mock_get_store):
        """Test search with vector store exception."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col1", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.search.side_effect = RuntimeError("Error")
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        results = manager.search("test query", collection_ids=["col1"])
        assert results == []

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_search_missing_metadata(self, mock_vector_store_cls, mock_get_store):
        """Test search with missing metadata fields."""
        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col1", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = [
            {"content": "Content", "score": 0.8, "metadata": {}}
        ]
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")
        results = manager.search("test query", collection_ids=["col1"])
        assert results == []

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    @patch("backend.knowledge_base.knowledge_base_manager.EnhancedVectorStore")
    def test_async_add_document(self, mock_vector_store_cls, mock_get_store):
        """Test async_add_document."""
        import asyncio

        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_doc = KnowledgeBaseDocument(
            collection_id="col123",
            filename="test.txt",
            content_hash="hash123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.get_document_by_hash.return_value = None
        mock_store.add_document.return_value = mock_doc
        mock_get_store.return_value = mock_store

        mock_vector_store = MagicMock()
        mock_vector_store.add.return_value = None
        mock_vector_store_cls.return_value = mock_vector_store

        manager = KnowledgeBaseManager(user_id="user123")

        async def test():
            result = await manager.async_add_document(
                "col123", "test.txt", "Test content"
            )
            assert result is not None

        asyncio.run(test())

    @patch("backend.knowledge_base.knowledge_base_manager.get_knowledge_base_store")
    def test_async_search(self, mock_get_store):
        """Test async_search."""
        import asyncio

        mock_store = MagicMock()
        mock_collection = KnowledgeBaseCollection(
            id="col123", user_id="user123", name="Test"
        )
        mock_store.get_collection.return_value = mock_collection
        mock_store.list_collections.return_value = [mock_collection]
        mock_get_store.return_value = mock_store

        manager = KnowledgeBaseManager(user_id="user123")
        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = []
        manager._vector_stores["col123"] = mock_vector_store

        async def test():
            results = await manager.async_search("test query")
            assert isinstance(results, list)

        asyncio.run(test())
