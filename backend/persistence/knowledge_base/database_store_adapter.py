"""Adapter to make async database store work with sync KnowledgeBaseStore interface."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.persistence.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
)
from backend.persistence.knowledge_base.database_knowledge_base_store import (
    DatabaseKnowledgeBaseStore,
)

logger = logging.getLogger(__name__)


class DatabaseStoreAdapter:
    """Adapter that wraps async DatabaseKnowledgeBaseStore to provide sync interface.

    This allows the database store to work with the existing sync KnowledgeBaseManager
    without requiring a full async refactor.
    """

    def __init__(self, db_store: DatabaseKnowledgeBaseStore):
        """Initialize adapter with database store."""
        self._db_store = db_store
        self._loop: asyncio.AbstractEventLoop | None = None

    def _run_async(self, coro):
        """Run async coroutine in sync context."""
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, we're in an async context
                # This shouldn't happen with our sync interface, but handle it
                import nest_asyncio

                try:
                    nest_asyncio.apply()
                    return loop.run_until_complete(coro)
                except ImportError:
                    logger.warning("nest_asyncio not available, creating new loop")
                    # Fall through to create new loop
            return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(coro)

    # Collection operations

    def create_collection(
        self, user_id: str, name: str, description: str | None = None
    ) -> KnowledgeBaseCollection:
        """Create a new collection."""
        return self._run_async(
            self._db_store.create_collection(user_id, name, description)
        )

    def get_collection(self, collection_id: str) -> KnowledgeBaseCollection | None:
        """Get a collection by ID."""
        return self._run_async(self._db_store.get_collection(collection_id))

    def list_collections(self, user_id: str) -> list[KnowledgeBaseCollection]:
        """List all collections for a user."""
        return self._run_async(self._db_store.list_collections(user_id))

    def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> KnowledgeBaseCollection | None:
        """Update a collection."""
        return self._run_async(
            self._db_store.update_collection(collection_id, name, description)
        )

    def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection and all its documents."""
        return self._run_async(self._db_store.delete_collection(collection_id))

    # Document operations

    def add_document(self, document: KnowledgeBaseDocument) -> KnowledgeBaseDocument:
        """Add a document to a collection."""
        return self._run_async(self._db_store.add_document(document))

    def get_document(self, document_id: str) -> KnowledgeBaseDocument | None:
        """Get a document by ID."""
        return self._run_async(self._db_store.get_document(document_id))

    def list_documents(self, collection_id: str) -> list[KnowledgeBaseDocument]:
        """List all documents in a collection."""
        return self._run_async(self._db_store.list_documents(collection_id))

    def delete_document(self, document_id: str) -> bool:
        """Delete a document."""
        return self._run_async(self._db_store.delete_document(document_id))

    def get_document_by_hash(self, content_hash: str) -> KnowledgeBaseDocument | None:
        """Find a document by its content hash (for deduplication)."""
        return self._run_async(self._db_store.get_document_by_hash(content_hash))

    def get_stats(self) -> dict[str, Any]:
        """Get storage statistics."""
        # Database store doesn't have get_stats, so compute it
        # This is a simple implementation - could be optimized with a SQL query
        # Use user_id from db_store if available, otherwise fall back to "default"
        user_id = getattr(self._db_store, 'user_id', None) or "default"
        collections = self.list_collections(user_id)
        total_docs = sum(c.document_count for c in collections)
        total_size = sum(c.total_size_bytes for c in collections)

        return {
            "total_collections": len(collections),
            "total_documents": total_docs,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }
