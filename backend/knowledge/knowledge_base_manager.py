"""Knowledge Base Manager - Integrates document storage with vector search."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.context.vector_store import EnhancedVectorStore
from backend.knowledge.query_expansion import QueryExpander
from backend.knowledge.smart_chunking import SmartChunker
from backend.persistence.data_models.knowledge_base import (
    DocumentChunk,
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
    KnowledgeBaseSearchResult,
)
from backend.persistence.knowledge_base.knowledge_base_store import (
    get_knowledge_base_store,
)

logger = logging.getLogger(__name__)


class KnowledgeBaseManager:
    """Manages knowledge base collections, documents, and vector search."""

    def __init__(self, user_id: str):
        """Initialize the knowledge base manager.

        Args:
            user_id: The user ID for this knowledge base

        """
        self.user_id = user_id
        self.store = get_knowledge_base_store()
        self._vector_stores: dict[str, EnhancedVectorStore] = {}
        self._chunker = SmartChunker()
        self._query_expander = QueryExpander(expand=True, use_patterns=True)

    def _get_vector_store(self, collection_id: str) -> EnhancedVectorStore:
        """Get or create a vector store for a collection."""
        if collection_id not in self._vector_stores:
            self._vector_stores[collection_id] = EnhancedVectorStore(
                collection_name=f'kb_{collection_id}',
                enable_cache=True,
                enable_reranking=True,
            )
        return self._vector_stores[collection_id]

    def _add_chunks_to_vector_store(
        self,
        collection_id: str,
        chunks: list[DocumentChunk],
        document: KnowledgeBaseDocument,
        filename: str,
    ) -> int:
        """Add chunks to vector store using a single batch call.

        Returns:
            Number of chunks successfully added
        """
        vector_store = self._get_vector_store(collection_id)

        if not chunks:
            return 0

        step_ids: list[str] = []
        roles: list[str] = []
        artifact_hashes: list[str | None] = []
        rationales: list[str | None] = []
        content_texts: list[str] = []
        metadatas: list[dict[str, Any] | None] = []

        for chunk in chunks:
            step_ids.append(chunk.id)
            roles.append('document')
            artifact_hashes.append(document.content_hash)
            rationales.append(f'Document: {filename}')
            content_texts.append(chunk.content)
            metadatas.append(
                {
                    'document_id': document.id,
                    'collection_id': collection_id,
                    'filename': filename,
                    'chunk_index': chunk.chunk_index,
                    **(chunk.metadata or {}),
                }
            )

        try:
            vector_store.add_batch(
                step_ids, roles, artifact_hashes, rationales, content_texts, metadatas
            )
            logger.info(
                "Added document '%s' to collection %s (%s/%s chunks)",
                filename,
                collection_id,
                len(chunks),
                len(chunks),
            )
            return len(chunks)
        except Exception as e:
            logger.error(
                'Failed to add %s chunks to vector store for document %s: %s',
                len(chunks),
                document.id,
                e,
            )
            return 0

    # Collection operations

    def create_collection(
        self, name: str, description: str | None = None
    ) -> KnowledgeBaseCollection:
        """Create a new knowledge base collection."""
        return self.store.create_collection(
            user_id=self.user_id,
            name=name,
            description=description,
        )

    def get_collection(self, collection_id: str) -> KnowledgeBaseCollection | None:
        """Get a collection by ID."""
        collection = self.store.get_collection(collection_id)
        if collection and collection.user_id != self.user_id:
            return None  # Access control
        return collection

    def list_collections(self) -> list[KnowledgeBaseCollection]:
        """List all collections for this user."""
        return self.store.list_collections(self.user_id)

    def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> KnowledgeBaseCollection | None:
        """Update a collection."""
        collection = self.get_collection(collection_id)
        if not collection:
            return None
        return self.store.update_collection(collection_id, name, description)

    def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection and all its documents."""
        collection = self.get_collection(collection_id)
        if not collection:
            return False

        # Delete from vector store first (before removing from store)
        try:
            vector_store = self._get_vector_store(collection_id)
            # Delete all chunks for this collection
            deleted_count = vector_store.delete_by_metadata(
                filter_metadata={'collection_id': collection_id}
            )
            logger.info(
                'Deleted %s vector chunks for collection %s',
                deleted_count,
                collection_id,
            )
        except Exception as e:
            logger.error(
                'Failed to delete vectors for collection %s: %s', collection_id, e
            )
            # Continue with store deletion even if vector deletion fails

        # Remove vector store reference
        self._vector_stores.pop(collection_id, None)

        # Delete from store (this will delete all documents)
        return self.store.delete_collection(collection_id)

    # Document operations

    def add_document(
        self,
        collection_id: str,
        filename: str,
        content: str,
        mime_type: str = 'text/plain',
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeBaseDocument | None:
        """Add a document to a collection.

        Args:
            collection_id: The collection to add to
            filename: The document filename
            content: The document content
            mime_type: MIME type of the document
            metadata: Optional metadata

        Returns:
            The created document, or None if collection doesn't exist

        """
        # Verify collection exists and user has access
        collection = self.get_collection(collection_id)
        if not collection:
            logger.error('Collection %s not found or access denied', collection_id)
            return None

        # Calculate content hash for deduplication
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Check if document already exists
        existing = self.store.get_document_by_hash(content_hash)
        if existing and existing.collection_id == collection_id:
            logger.info('Document with hash %s already exists', content_hash)
            return existing

        # Create document
        document = KnowledgeBaseDocument(
            collection_id=collection_id,
            filename=filename,
            content_hash=content_hash,
            file_size_bytes=len(content.encode()),
            mime_type=mime_type,
            content_preview=content[:500] if len(content) > 500 else content,
            chunk_count=0,  # Will be updated after chunking
        )

        # Chunk the content
        chunks = self._chunk_content(content, document.id, metadata, filename=filename)
        document.chunk_count = len(chunks)

        # Store document first (so we have an ID)
        document = self.store.add_document(document)

        # Add chunks to vector store with error handling
        chunks_added = self._add_chunks_to_vector_store(
            collection_id, chunks, document, filename
        )
        document.chunk_count = chunks_added

        if chunks_added < len(chunks):
            logger.warning(
                "Document '%s' stored but vector chunks may be incomplete. Consider re-uploading the document.",
                filename,
            )

        return document

    async def async_add_document(
        self,
        collection_id: str,
        filename: str,
        content: str,
        mime_type: str = 'text/plain',
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeBaseDocument | None:
        """Async wrapper for adding a document without blocking.

        Performs chunking and vector insertion in a thread to keep the event loop responsive.
        """
        return await asyncio.to_thread(
            self.add_document,
            collection_id,
            filename,
            content,
            mime_type,
            metadata,
        )

    def _chunk_content(
        self,
        content: str,
        document_id: str,
        metadata: dict[str, Any] | None = None,
        filename: str | None = None,
    ) -> list[DocumentChunk]:
        """Split content into chunks for vector storage.

        Delegates to SmartChunker which handles all strategies:
        - Markdown, JSON, YAML: structure-aware splitting.
        - Code files: AST-aware (tree-sitter) with sliding-window fallback.
        - Plain text: sliding-window fallback.
        """
        file_type = self._chunker.get_file_type(filename)

        if file_type == 'markdown':
            return self._chunker.chunk_markdown(content, document_id, metadata)
        if file_type == 'json':
            return self._chunker.chunk_json(content, document_id, metadata)
        if file_type == 'yaml':
            return self._chunker.chunk_yaml(content, document_id, metadata)

        if filename:
            return self._chunker.chunk_code(content, document_id, filename, metadata)

        return self._chunker.chunk_text_fallback(content, document_id, metadata)

    def get_document(self, document_id: str) -> KnowledgeBaseDocument | None:
        """Get a document by ID."""
        document = self.store.get_document(document_id)
        if document:
            # Verify user has access
            collection = self.get_collection(document.collection_id)
            if not collection:
                return None
        return document

    def list_documents(self, collection_id: str) -> list[KnowledgeBaseDocument]:
        """List all documents in a collection."""
        collection = self.get_collection(collection_id)
        if not collection:
            return []
        return self.store.list_documents(collection_id)

    def delete_document(self, document_id: str) -> bool:
        """Delete a document from its collection.

        Deletes both the document metadata and all associated vector chunks.
        """
        document = self.get_document(document_id)
        if not document:
            return False

        collection_id = document.collection_id

        # Delete from vector store first
        try:
            vector_store = self._get_vector_store(collection_id)
            # Delete all chunks for this document
            deleted_count = vector_store.delete_by_metadata(
                filter_metadata={'document_id': document_id}
            )
            logger.info(
                'Deleted %s vector chunks for document %s', deleted_count, document_id
            )
        except Exception as e:
            logger.error('Failed to delete vectors for document %s: %s', document_id, e)
            # Continue with store deletion even if vector deletion fails

        # Delete from store
        return self.store.delete_document(document_id)

    # Search operations

    def search(
        self,
        query: str,
        collection_ids: list[str] | None = None,
        top_k: int = 5,
        relevance_threshold: float = 0.7,
        expand_query: bool = True,
    ) -> list[KnowledgeBaseSearchResult]:
        """Search across knowledge base collections.

        Searches all specified collections in parallel, then merges and
        sorts results by relevance. Uses query expansion with synonyms
        to improve recall.

        Args:
            query: The search query
            collection_ids: List of collection IDs to search (or None for all)
            top_k: Number of results to return
            relevance_threshold: Minimum relevance score (0-1)
            expand_query: Whether to expand query with synonyms

        Returns:
            List of search results, sorted by relevance

        """
        if collection_ids is None:
            collections = self.list_collections()
            collection_ids = [c.id for c in collections]

        # Filter to accessible collections
        accessible = []
        for collection_id in collection_ids:
            collection = self.get_collection(collection_id)
            if collection:
                accessible.append(collection_id)

        if not accessible:
            return []

        # Expand query with synonyms for better recall
        expanded_queries = [query]
        if expand_query:
            expanded_queries = self._query_expander.expand_query(query)

        # Search all accessible collections in parallel
        all_results: list[KnowledgeBaseSearchResult] = []

        def _search_collection(
            cid: str, search_query: str
        ) -> list[KnowledgeBaseSearchResult]:
            vector_store = self._get_vector_store(cid)
            results: list[KnowledgeBaseSearchResult] = []
            try:
                raw_results = vector_store.search(
                    query=search_query,
                    k=top_k,
                    filter_metadata={'collection_id': cid},
                )
                for result in raw_results:
                    score = result.get('score', 0.0)
                    if score < relevance_threshold:
                        continue
                    meta = result.get('metadata', {})
                    results.append(
                        KnowledgeBaseSearchResult(
                            document_id=meta.get('document_id', ''),
                            collection_id=cid,
                            filename=meta.get('filename', ''),
                            chunk_content=result.get('content', ''),
                            relevance_score=score,
                            metadata=meta,
                        )
                    )
            except Exception as e:
                logger.error('Error searching collection %s: %s', cid, e)
            return results

        with ThreadPoolExecutor(
            max_workers=min(len(accessible) * len(expanded_queries), 16)
        ) as pool:
            futures = {}
            for cid in accessible:
                for eq in expanded_queries:
                    futures[pool.submit(_search_collection, cid, eq)] = (cid, eq)

            seen_chunks: dict[str, KnowledgeBaseSearchResult] = {}
            for future in as_completed(futures):
                cid, eq = futures[future]
                try:
                    results = future.result()
                    for r in results:
                        chunk_idx = (
                            r.metadata.get('chunk_index', 0) if r.metadata else 0
                        )
                        chunk_key = f'{r.document_id}:{chunk_idx}'
                        if (
                            chunk_key not in seen_chunks
                            or r.relevance_score
                            > seen_chunks[chunk_key].relevance_score
                        ):
                            seen_chunks[chunk_key] = r
                except Exception as e:
                    logger.error(
                        'Error searching collection %s with query %s: %s', cid, eq, e
                    )

            all_results = list(seen_chunks.values())

        # Sort by relevance and return top results
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)
        return all_results[:top_k]

    async def async_search(
        self,
        query: str,
        collection_ids: list[str] | None = None,
        top_k: int = 5,
        relevance_threshold: float = 0.7,
        expand_query: bool = True,
    ) -> list[KnowledgeBaseSearchResult]:
        """Async wrapper for search, offloading blocking work to a thread."""
        return await asyncio.to_thread(
            self.search,
            query,
            collection_ids,
            top_k,
            relevance_threshold,
            expand_query,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get knowledge base statistics."""
        collections = self.list_collections()
        total_docs = sum(c.document_count for c in collections)
        total_size = sum(c.total_size_bytes for c in collections)

        return {
            'total_collections': len(collections),
            'total_documents': total_docs,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'collections': [
                {
                    'id': c.id,
                    'name': c.name,
                    'document_count': c.document_count,
                    'size_mb': round(c.total_size_bytes / (1024 * 1024), 2),
                }
                for c in collections
            ],
        }
