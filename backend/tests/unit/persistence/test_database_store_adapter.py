"""Tests for DatabaseStoreAdapter — sync wrapper for async database store.

Tests cover:
- Collection operations (create, get, list, update, delete)
- Document operations (add, get, list, delete, get_by_hash)
- Statistics aggregation
- Async-to-sync bridging
- Error handling
"""

from __future__ import annotations

from typing import Any, cast

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.persistence.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
)
from backend.persistence.knowledge_base.database_store_adapter import DatabaseStoreAdapter


@pytest.fixture
def mock_db_store() -> MagicMock:
    """Provide a mocked DatabaseKnowledgeBaseStore."""
    return MagicMock()


@pytest.fixture
def adapter(mock_db_store: MagicMock) -> DatabaseStoreAdapter:
    """Provide a DatabaseStoreAdapter with mocked backend."""
    return DatabaseStoreAdapter(mock_db_store)


@pytest.fixture
def example_collection() -> KnowledgeBaseCollection:
    """Provide an example collection."""
    return KnowledgeBaseCollection(
        id="col_123",
        user_id="user_1",
        name="Test Collection",
        description="A test knowledge base",
        document_count=5,
        total_size_bytes=10240,
    )


@pytest.fixture
def example_document() -> KnowledgeBaseDocument:
    """Provide an example document."""
    return KnowledgeBaseDocument(
        id="doc_123",
        collection_id="col_123",
        filename="test.txt",
        content_hash="abc123def456",
        file_size_bytes=1024,
        mime_type="text/plain",
        content_preview="This is a test document",
        chunk_count=2,
    )


class TestCollectionOperations:
    """Test collection-related operations."""

    def test_create_collection(
        self, adapter: DatabaseStoreAdapter, example_collection: KnowledgeBaseCollection
    ) -> None:
        """Test creating a new collection."""
        cast(Any, adapter._db_store).create_collection = AsyncMock(return_value=example_collection)

        result = adapter.create_collection("user_1", "Test Collection", "A test KB")

        assert result is not None
        assert result.id == "col_123"
        assert result is not None
        assert result.name == "Test Collection"
        assert result is not None
        assert result.description == "A test knowledge base"
        cast(Any, adapter._db_store).create_collection.assert_called_once_with(
            "user_1", "Test Collection", "A test KB"
        )

    def test_create_collection_without_description(
        self, adapter: DatabaseStoreAdapter, example_collection: KnowledgeBaseCollection
    ) -> None:
        """Test creating a collection without description."""
        cast(Any, adapter._db_store).create_collection = AsyncMock(return_value=example_collection)

        result = adapter.create_collection("user_1", "Test Collection")

        assert result is not None
        assert result.name == "Test Collection"
        cast(Any, adapter._db_store).create_collection.assert_called_once_with(
            "user_1", "Test Collection", None
        )

    def test_get_collection(
        self, adapter: DatabaseStoreAdapter, example_collection: KnowledgeBaseCollection
    ) -> None:
        """Test retrieving a collection."""
        cast(Any, adapter._db_store).get_collection = AsyncMock(return_value=example_collection)

        result = adapter.get_collection("col_123")

        assert result is not None
        assert result.id == "col_123"
        assert result is not None
        assert result.name == "Test Collection"
        cast(Any, adapter._db_store).get_collection.assert_called_once_with("col_123")

    def test_get_collection_not_found(self, adapter: DatabaseStoreAdapter) -> None:
        """Test getting a collection that doesn't exist."""
        cast(Any, adapter._db_store).get_collection = AsyncMock(return_value=None)

        result = adapter.get_collection("nonexistent")

        assert result is None

    def test_list_collections(
        self, adapter: DatabaseStoreAdapter, example_collection: KnowledgeBaseCollection
    ) -> None:
        """Test listing all collections for a user."""
        cast(Any, adapter._db_store).list_collections = AsyncMock(
            return_value=[example_collection]
        )

        result = adapter.list_collections("user_1")

        assert len(result) == 1
        assert result[0].name == "Test Collection"
        cast(Any, adapter._db_store).list_collections.assert_called_once_with("user_1")

    def test_list_collections_empty(self, adapter: DatabaseStoreAdapter) -> None:
        """Test listing collections when user has none."""
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[])

        result = adapter.list_collections("user_1")

        assert result == []

    def test_list_collections_multiple(self, adapter: DatabaseStoreAdapter) -> None:
        """Test listing multiple collections."""
        col1 = KnowledgeBaseCollection(
            id="col_1", user_id="user_1", name="Collection 1"
        )
        col2 = KnowledgeBaseCollection(
            id="col_2", user_id="user_1", name="Collection 2"
        )
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[col1, col2])

        result = adapter.list_collections("user_1")

        assert len(result) == 2
        assert result[0].name == "Collection 1"
        assert result[1].name == "Collection 2"

    def test_update_collection_name(
        self, adapter: DatabaseStoreAdapter, example_collection: KnowledgeBaseCollection
    ) -> None:
        """Test updating collection name."""
        updated = KnowledgeBaseCollection(
            id="col_123",
            user_id="user_1",
            name="Updated Name",
            description="A test KB",
            document_count=5,
            total_size_bytes=10240,
        )
        cast(Any, adapter._db_store).update_collection = AsyncMock(return_value=updated)

        result = adapter.update_collection("col_123", name="Updated Name")

        assert result is not None
        assert result.name == "Updated Name"
        cast(Any, adapter._db_store).update_collection.assert_called_once_with(
            "col_123", "Updated Name", None
        )

    def test_update_collection_description(self, adapter: DatabaseStoreAdapter) -> None:
        """Test updating collection description."""
        updated = KnowledgeBaseCollection(
            id="col_123",
            user_id="user_1",
            name="Test Collection",
            description="New description",
        )
        cast(Any, adapter._db_store).update_collection = AsyncMock(return_value=updated)

        result = adapter.update_collection("col_123", description="New description")

        assert result is not None
        assert result.description == "New description"

    def test_update_collection_both(self, adapter: DatabaseStoreAdapter) -> None:
        """Test updating both name and description."""
        updated = KnowledgeBaseCollection(
            id="col_123",
            user_id="user_1",
            name="New Name",
            description="New description",
        )
        cast(Any, adapter._db_store).update_collection = AsyncMock(return_value=updated)

        result = adapter.update_collection(
            "col_123", name="New Name", description="New description"
        )

        assert result is not None
        assert result.name == "New Name"
        assert result is not None
        assert result.description == "New description"

    def test_update_collection_not_found(self, adapter: DatabaseStoreAdapter) -> None:
        """Test updating a collection that doesn't exist."""
        cast(Any, adapter._db_store).update_collection = AsyncMock(return_value=None)

        result = adapter.update_collection("nonexistent", name="New Name")

        assert result is None

    def test_delete_collection(self, adapter: DatabaseStoreAdapter) -> None:
        """Test deleting a collection."""
        cast(Any, adapter._db_store).delete_collection = AsyncMock(return_value=True)

        result = adapter.delete_collection("col_123")

        assert result is True
        cast(Any, adapter._db_store).delete_collection.assert_called_once_with("col_123")

    def test_delete_collection_not_found(self, adapter: DatabaseStoreAdapter) -> None:
        """Test deleting a collection that doesn't exist."""
        cast(Any, adapter._db_store).delete_collection = AsyncMock(return_value=False)

        result = adapter.delete_collection("nonexistent")

        assert result is False


class TestDocumentOperations:
    """Test document-related operations."""

    def test_add_document(
        self, adapter: DatabaseStoreAdapter, example_document: KnowledgeBaseDocument
    ) -> None:
        """Test adding a document."""
        cast(Any, adapter._db_store).add_document = AsyncMock(return_value=example_document)

        result = adapter.add_document(example_document)

        assert result is not None
        assert result.id == "doc_123"
        assert result is not None
        assert result.filename == "test.txt"
        cast(Any, adapter._db_store).add_document.assert_called_once_with(example_document)

    def test_get_document(
        self, adapter: DatabaseStoreAdapter, example_document: KnowledgeBaseDocument
    ) -> None:
        """Test retrieving a document."""
        cast(Any, adapter._db_store).get_document = AsyncMock(return_value=example_document)

        result = adapter.get_document("doc_123")

        assert result is not None
        assert result.id == "doc_123"
        assert result is not None
        assert result.filename == "test.txt"
        cast(Any, adapter._db_store).get_document.assert_called_once_with("doc_123")

    def test_get_document_not_found(self, adapter: DatabaseStoreAdapter) -> None:
        """Test retrieving a document that doesn't exist."""
        cast(Any, adapter._db_store).get_document = AsyncMock(return_value=None)

        result = adapter.get_document("nonexistent")

        assert result is None

    def test_list_documents(
        self, adapter: DatabaseStoreAdapter, example_document: KnowledgeBaseDocument
    ) -> None:
        """Test listing documents in a collection."""
        cast(Any, adapter._db_store).list_documents = AsyncMock(return_value=[example_document])

        result = adapter.list_documents("col_123")

        assert len(result) == 1
        assert result[0].filename == "test.txt"
        cast(Any, adapter._db_store).list_documents.assert_called_once_with("col_123")

    def test_list_documents_empty(self, adapter: DatabaseStoreAdapter) -> None:
        """Test listing documents in an empty collection."""
        cast(Any, adapter._db_store).list_documents = AsyncMock(return_value=[])

        result = adapter.list_documents("col_123")

        assert result == []

    def test_list_documents_multiple(self, adapter: DatabaseStoreAdapter) -> None:
        """Test listing multiple documents."""
        doc1 = KnowledgeBaseDocument(
            id="doc_1",
            collection_id="col_123",
            filename="doc1.txt",
            content_hash="hash1",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        doc2 = KnowledgeBaseDocument(
            id="doc_2",
            collection_id="col_123",
            filename="doc2.txt",
            content_hash="hash2",
            file_size_bytes=200,
            mime_type="text/plain",
        )
        cast(Any, adapter._db_store).list_documents = AsyncMock(return_value=[doc1, doc2])

        result = adapter.list_documents("col_123")

        assert len(result) == 2
        assert result[0].filename == "doc1.txt"
        assert result[1].filename == "doc2.txt"

    def test_delete_document(self, adapter: DatabaseStoreAdapter) -> None:
        """Test deleting a document."""
        cast(Any, adapter._db_store).delete_document = AsyncMock(return_value=True)

        result = adapter.delete_document("doc_123")

        assert result is True
        cast(Any, adapter._db_store).delete_document.assert_called_once_with("doc_123")

    def test_delete_document_not_found(self, adapter: DatabaseStoreAdapter) -> None:
        """Test deleting a document that doesn't exist."""
        cast(Any, adapter._db_store).delete_document = AsyncMock(return_value=False)

        result = adapter.delete_document("nonexistent")

        assert result is False

    def test_get_document_by_hash(
        self, adapter: DatabaseStoreAdapter, example_document: KnowledgeBaseDocument
    ) -> None:
        """Test finding a document by its content hash."""
        cast(Any, adapter._db_store).get_document_by_hash = AsyncMock(
            return_value=example_document
        )

        result = adapter.get_document_by_hash("abc123def456")

        assert result is not None
        assert result.id == "doc_123"
        cast(Any, adapter._db_store).get_document_by_hash.assert_called_once_with("abc123def456")

    def test_get_document_by_hash_not_found(
        self, adapter: DatabaseStoreAdapter
    ) -> None:
        """Test finding a document by hash when it doesn't exist."""
        cast(Any, adapter._db_store).get_document_by_hash = AsyncMock(return_value=None)

        result = adapter.get_document_by_hash("nonexistent_hash")

        assert result is None


class TestStatistics:
    """Test statistics aggregation."""

    def test_get_stats_single_collection(self, adapter: DatabaseStoreAdapter) -> None:
        """Test getting stats with one collection."""
        col = KnowledgeBaseCollection(
            id="col_1",
            user_id="default",
            name="Test",
            document_count=5,
            total_size_bytes=5120,
        )
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[col])

        stats = adapter.get_stats()

        assert stats["total_collections"] == 1
        assert stats["total_documents"] == 5
        assert stats["total_size_bytes"] == 5120
        assert stats["total_size_mb"] == round(5120 / (1024 * 1024), 2)

    def test_get_stats_multiple_collections(
        self, adapter: DatabaseStoreAdapter
    ) -> None:
        """Test getting stats with multiple collections."""
        col1 = KnowledgeBaseCollection(
            id="col_1",
            user_id="default",
            name="Col1",
            document_count=5,
            total_size_bytes=1024,
        )
        col2 = KnowledgeBaseCollection(
            id="col_2",
            user_id="default",
            name="Col2",
            document_count=10,
            total_size_bytes=2048,
        )
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[col1, col2])

        stats = adapter.get_stats()

        assert stats["total_collections"] == 2
        assert stats["total_documents"] == 15
        assert stats["total_size_bytes"] == 3072

    def test_get_stats_empty(self, adapter: DatabaseStoreAdapter) -> None:
        """Test getting stats with no collections."""
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[])

        stats = adapter.get_stats()

        assert stats["total_collections"] == 0
        assert stats["total_documents"] == 0
        assert stats["total_size_bytes"] == 0
        assert stats["total_size_mb"] == 0.0

    def test_get_stats_large_size(self, adapter: DatabaseStoreAdapter) -> None:
        """Test stats calculation with large sizes."""
        col = KnowledgeBaseCollection(
            id="col_1",
            user_id="default",
            name="Large",
            document_count=1,
            total_size_bytes=1024 * 1024 * 500,  # 500 MB
        )
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[col])

        stats = adapter.get_stats()

        assert stats["total_size_mb"] == 500.0


class TestAsyncBridging:
    """Test async-to-sync bridging functionality."""

    def test_run_async_with_existing_loop(self, adapter: DatabaseStoreAdapter) -> None:
        """Test _run_async with existing event loop."""

        async def dummy_coro():
            return "result"

        result = adapter._run_async(dummy_coro())
        assert result == "result"

    def test_run_async_handles_coroutine(self, adapter: DatabaseStoreAdapter) -> None:
        """Test _run_async correctly executes coroutine."""
        call_count = 0

        async def counting_coro():
            nonlocal call_count
            call_count += 1
            return call_count

        result = adapter._run_async(counting_coro())
        assert result == 1

    def test_multiple_async_calls(
        self, adapter: DatabaseStoreAdapter, example_collection: KnowledgeBaseCollection
    ) -> None:
        """Test multiple async calls are properly bridged."""
        cast(Any, adapter._db_store).create_collection = AsyncMock(return_value=example_collection)
        cast(Any, adapter._db_store).get_collection = AsyncMock(return_value=example_collection)

        col1 = adapter.create_collection("user_1", "Col1")
        col2 = adapter.get_collection(col1.id)

        assert col2 is not None
        assert col1.id == col2.id
        assert cast(Any, adapter._db_store).create_collection.called
        assert cast(Any, adapter._db_store).get_collection.called


class TestIntegrationScenarios:
    """Test realistic usage scenarios."""

    def test_create_and_list_workflow(self, adapter: DatabaseStoreAdapter) -> None:
        """Test creating a collection and listing it."""
        col = KnowledgeBaseCollection(id="col_1", user_id="user_1", name="My KB")
        cast(Any, adapter._db_store).create_collection = AsyncMock(return_value=col)
        cast(Any, adapter._db_store).list_collections = AsyncMock(return_value=[col])

        # Create
        created = adapter.create_collection("user_1", "My KB")
        assert created.id == "col_1"

        # List
        collections = adapter.list_collections("user_1")
        assert len(collections) == 1
        assert collections[0].name == "My KB"

    def test_add_and_list_documents_workflow(
        self, adapter: DatabaseStoreAdapter
    ) -> None:
        """Test adding documents and listing them."""
        doc1 = KnowledgeBaseDocument(
            id="doc_1",
            collection_id="col_1",
            filename="file1.txt",
            content_hash="hash1",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        doc2 = KnowledgeBaseDocument(
            id="doc_2",
            collection_id="col_1",
            filename="file2.txt",
            content_hash="hash2",
            file_size_bytes=200,
            mime_type="text/plain",
        )
        cast(Any, adapter._db_store).add_document = AsyncMock(side_effect=[doc1, doc2])
        cast(Any, adapter._db_store).list_documents = AsyncMock(return_value=[doc1, doc2])

        # Add documents
        adapter.add_document(doc1)
        adapter.add_document(doc2)

        # List documents
        documents = adapter.list_documents("col_1")
        assert len(documents) == 2
        assert documents[0].filename == "file1.txt"
        assert documents[1].filename == "file2.txt"

    def test_deduplication_by_hash(self, adapter: DatabaseStoreAdapter) -> None:
        """Test finding duplicate documents by hash."""
        doc = KnowledgeBaseDocument(
            id="doc_1",
            collection_id="col_1",
            filename="file.txt",
            content_hash="abc123",
            file_size_bytes=100,
            mime_type="text/plain",
        )
        cast(Any, adapter._db_store).get_document_by_hash = AsyncMock(return_value=doc)

        # Check if document already exists by hash
        existing = adapter.get_document_by_hash("abc123")

        assert existing is not None
        assert existing.id == "doc_1"
