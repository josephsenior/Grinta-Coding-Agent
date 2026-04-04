"""In-memory storage for knowledge base collections and documents.

This provides a simple, file-based persistence layer for the knowledge base
without requiring database migrations.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from datetime import UTC

from backend.persistence.locations import get_active_local_data_root

from backend.persistence.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
)

logger = logging.getLogger(__name__)


class KnowledgeBaseStore:
    """Thread-safe in-memory store for knowledge base data."""

    def __init__(self, storage_dir: Path | None = None):
        """Initialize the knowledge base store.

        Args:
            storage_dir: Directory to persist data. If None, uses ~/.app/kb/

        """
        self._lock = Lock()
        self._collections: dict[str, KnowledgeBaseCollection] = {}
        self._documents: dict[str, KnowledgeBaseDocument] = {}
        self._collection_documents: dict[
            str, list[str]
        ] = {}  # collection_id -> [doc_ids]

        # Setup storage directory
        if storage_dir is None:
            storage_dir = Path(get_active_local_data_root()) / 'kb'
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.collections_file = self.storage_dir / 'collections.json'
        self.documents_file = self.storage_dir / 'documents.json'

        # Load existing data
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load collections and documents from disk."""
        try:
            if self.collections_file.exists():
                with open(self.collections_file, encoding='utf-8') as f:
                    data = json.load(f)
                    self._collections = {
                        k: KnowledgeBaseCollection.model_validate(v)
                        for k, v in data.get('collections', {}).items()
                    }
                    self._collection_documents = data.get('collection_documents', {})
                logger.info('Loaded %d collections from disk', len(self._collections))

            if self.documents_file.exists():
                with open(self.documents_file, encoding='utf-8') as f:
                    data = json.load(f)
                    self._documents = {
                        k: KnowledgeBaseDocument.model_validate(v)
                        for k, v in data.get('documents', {}).items()
                    }
                logger.info('Loaded %d documents from disk', len(self._documents))

        except Exception as e:
            logger.error('Failed to load knowledge base data from disk: %s', e)

    def _save_to_disk(self) -> None:
        """Save collections and documents to disk."""
        try:
            # Save collections
            with open(self.collections_file, 'w', encoding='utf-8') as f:
                data = {
                    'collections': {
                        k: v.model_dump(mode='json')
                        for k, v in self._collections.items()
                    },
                    'collection_documents': self._collection_documents,
                }
                json.dump(data, f, indent=2, default=str)

            # Save documents
            with open(self.documents_file, 'w', encoding='utf-8') as f:
                data = {
                    'documents': {
                        k: v.model_dump(mode='json') for k, v in self._documents.items()
                    }
                }
                json.dump(data, f, indent=2, default=str)

            logger.debug('Saved knowledge base data to disk')

        except Exception as e:
            logger.error('Failed to save knowledge base data to disk: %s', e)

    # Collection operations

    def create_collection(
        self, user_id: str, name: str, description: str | None = None
    ) -> KnowledgeBaseCollection:
        """Create a new collection."""
        with self._lock:
            collection = KnowledgeBaseCollection(
                user_id=user_id,
                name=name,
                description=description,
                document_count=0,
                total_size_bytes=0,
            )
            self._collections[collection.id] = collection
            self._collection_documents[collection.id] = []
            self._save_to_disk()
            logger.info(
                'Created collection: %s (ID: %s)', collection.name, collection.id
            )
            return collection

    def get_collection(self, collection_id: str) -> KnowledgeBaseCollection | None:
        """Get a collection by ID."""
        with self._lock:
            return self._collections.get(collection_id)

    def list_collections(self, user_id: str) -> list[KnowledgeBaseCollection]:
        """List all collections for a user."""
        with self._lock:
            return [c for c in self._collections.values() if c.user_id == user_id]

    def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> KnowledgeBaseCollection | None:
        """Update a collection."""
        with self._lock:
            collection = self._collections.get(collection_id)
            if not collection:
                return None

            if name is not None:
                collection.name = name
            if description is not None:
                collection.description = description

            from datetime import datetime

            collection.updated_at = datetime.now(UTC)
            self._save_to_disk()
            return collection

    def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection and all its documents."""
        with self._lock:
            if collection_id not in self._collections:
                return False

            # Delete all documents in the collection
            doc_ids = self._collection_documents.get(collection_id, [])
            for doc_id in doc_ids:
                self._documents.pop(doc_id, None)

            # Delete the collection
            self._collections.pop(collection_id)
            self._collection_documents.pop(collection_id, None)
            self._save_to_disk()
            logger.info('Deleted collection: %s', collection_id)
            return True

    # Document operations

    def add_document(self, document: KnowledgeBaseDocument) -> KnowledgeBaseDocument:
        """Add a document to a collection."""
        with self._lock:
            self._documents[document.id] = document

            # Add to collection's document list
            if document.collection_id not in self._collection_documents:
                self._collection_documents[document.collection_id] = []
            self._collection_documents[document.collection_id].append(document.id)

            # Update collection stats
            collection = self._collections.get(document.collection_id)
            if collection:
                collection.document_count += 1
                collection.total_size_bytes += document.file_size_bytes
                from datetime import datetime

                collection.updated_at = datetime.now(UTC)

            self._save_to_disk()
            logger.info('Added document: %s (ID: %s)', document.filename, document.id)
            return document

    def get_document(self, document_id: str) -> KnowledgeBaseDocument | None:
        """Get a document by ID."""
        with self._lock:
            return self._documents.get(document_id)

    def list_documents(self, collection_id: str) -> list[KnowledgeBaseDocument]:
        """List all documents in a collection."""
        with self._lock:
            doc_ids = self._collection_documents.get(collection_id, [])
            return [
                self._documents[doc_id]
                for doc_id in doc_ids
                if doc_id in self._documents
            ]

    def delete_document(self, document_id: str) -> bool:
        """Delete a document."""
        with self._lock:
            document = self._documents.get(document_id)
            if not document:
                return False

            # Remove from collection's document list
            if document.collection_id in self._collection_documents:
                doc_list = self._collection_documents[document.collection_id]
                try:
                    doc_list.remove(document_id)
                except ValueError:
                    # Document ID not in list - already removed or corrupted state
                    logger.warning(
                        'Document %s not found in collection %s document list',
                        document_id,
                        document.collection_id,
                    )

            # Update collection stats with validation
            collection = self._collections.get(document.collection_id)
            if collection:
                # Prevent negative counts from corrupting state
                collection.document_count = max(0, collection.document_count - 1)
                collection.total_size_bytes = max(
                    0, collection.total_size_bytes - document.file_size_bytes
                )
                from datetime import datetime

                collection.updated_at = datetime.now(UTC)

            # Delete the document
            self._documents.pop(document_id)
            self._save_to_disk()
            logger.info('Deleted document: %s', document_id)
            return True

    def get_document_by_hash(self, content_hash: str) -> KnowledgeBaseDocument | None:
        """Find a document by its content hash (for deduplication)."""
        with self._lock:
            for doc in self._documents.values():
                if doc.content_hash == content_hash:
                    return doc
            return None

    def get_stats(self) -> dict[str, Any]:
        """Get storage statistics."""
        with self._lock:
            total_collections = len(self._collections)
            total_documents = len(self._documents)
            total_size = sum(d.file_size_bytes for d in self._documents.values())

            return {
                'total_collections': total_collections,
                'total_documents': total_documents,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
            }


# Global instance
_store: KnowledgeBaseStore | Any | None = None


def get_knowledge_base_store() -> KnowledgeBaseStore | Any:
    """Get the global knowledge base store instance.

    Storage backend is determined by APP_KB_STORAGE_TYPE environment variable:
    - "database" or "db": Use PostgreSQL database storage
    - "file" or unset: Use file-based storage (default)
    """
    global _store
    if _store is None:
        # Check if database storage is requested
        storage_type = os.getenv('APP_KB_STORAGE_TYPE', 'file').lower()
        if storage_type in ('database', 'db'):
            # Use database-backed store
            from backend.persistence.knowledge_base.database_knowledge_base_store import (
                DatabaseKnowledgeBaseStore,
            )
            from backend.persistence.knowledge_base.database_store_adapter import (
                DatabaseStoreAdapter,
            )

            db_store = DatabaseKnowledgeBaseStore()
            _store = DatabaseStoreAdapter(db_store)
        else:
            # File-based store (default)
            storage_dir = os.getenv('APP_KB_STORAGE_PATH')
            if storage_dir:
                _store = KnowledgeBaseStore(storage_dir=Path(storage_dir))
            else:
                _store = KnowledgeBaseStore(storage_dir=None)
    return _store
