"""Local vector store implementation using ChromaDB."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VectorBackend(ABC):
    """Abstract base class for vector storage backends."""

    @abstractmethod
    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a document to the vector store."""

    @abstractmethod
    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search for similar documents."""

    @abstractmethod
    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents matching metadata filters."""

    @abstractmethod
    def delete_by_ids(self, ids: list[str]) -> int:
        """Delete documents by their IDs."""

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Get statistics about the vector store."""


class ChromaDBBackend(VectorBackend):
    """Local ChromaDB backend for vector storage."""

    def __init__(
        self,
        collection_name: str = 'APP_memory',
        persist_directory: Path | None = None,
    ) -> None:
        r"""Initialize ChromaDB local vector store.

        Args:
            collection_name: Name of ChromaDB collection
            persist_directory: Directory for persistent storage

        """
        if persist_directory is None:
            persist_directory = Path.home() / '.grinta' / 'memory' / 'chroma'
        persist_directory.mkdir(parents=True, exist_ok=True)

        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(
            path=str(persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )

        # Embedding model — lazy-loaded in a background thread so __init__ is instant.
        self._model_name = os.getenv('EMBEDDING_MODEL', 'nomic-ai/nomic-embed-text-v1.5')
        self._model: Any | None = None
        self._model_lock = threading.Lock()

        # Load or create collection, handling embedding model changes
        self._collection_name = collection_name
        try:
            self.collection = self.client.get_collection(name=collection_name)
            stored_model = self.collection.metadata.get('embedding_model', '')
            if stored_model and stored_model != self._model_name:
                logger.info(
                    'Embedding model changed (%s → %s), recreating collection',
                    stored_model, self._model_name,
                )
                self.client.delete_collection(name=collection_name)
                self.collection = self._create_collection(collection_name)
            else:
                logger.info(
                    'Loaded ChromaDB collection with %s documents',
                    self.collection.count(),
                )
        except Exception:
            self.collection = self._create_collection(collection_name)

        # Start background model loading so it's ready by first user message
        threading.Thread(target=self._load_model, daemon=True).start()

    def _create_collection(self, name: str) -> Any:
        """Create a new ChromaDB collection with model metadata."""
        collection = self.client.create_collection(
            name=name,
            metadata={'hnsw:space': 'cosine', 'embedding_model': self._model_name},
        )
        logger.info('Created new ChromaDB collection')
        return collection

    def _load_model(self) -> None:
        """Load the embedding model. Thread-safe, called from background thread."""
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            logger.info("Loading embedding model '%s'…", self._model_name)
            from sentence_transformers import SentenceTransformer

            with contextlib.redirect_stderr(io.StringIO()), \
                 contextlib.redirect_stdout(io.StringIO()):
                self._model = SentenceTransformer(
                    self._model_name, trust_remote_code=True,
                )
            logger.info('Embedding model loaded')

    @property
    def model(self) -> Any:
        """Lazy-loaded embedding model. Blocks on first access if still loading."""
        if self._model is None:
            self._load_model()
        return self._model

    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert a new document embedding into the local ChromaDB collection."""
        text = self._prepare_text(rationale, content_text)
        embedding = self.model.encode(text, show_progress_bar=False).tolist()

        doc_metadata = {
            'step_id': step_id,
            'role': role,
            'timestamp': time.time(),
            **(metadata or {}),
        }
        if artifact_hash:
            doc_metadata['artifact_hash'] = artifact_hash

        self.collection.add(
            ids=[step_id],
            embeddings=[embedding],  # type: ignore[arg-type]
            documents=[text[:2000]],
            metadatas=[doc_metadata],
        )

    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search the collection for the most similar documents to the query."""
        if self.collection.count() == 0:
            return []

        query_embedding = self.model.encode(query, show_progress_bar=False).tolist()
        results = self.collection.query(
            query_embeddings=[query_embedding],  # type: ignore[arg-type]
            n_results=min(k, self.collection.count()),
            where=filter_metadata,
            include=['documents', 'metadatas', 'distances'],
        )

        if (
            not results['ids']
            or not results['documents']
            or not results['metadatas']
            or not results['distances']
        ):
            return []

        return [
            {
                'step_id': results['ids'][0][i],
                'score': 1.0 - results['distances'][0][i],
                'excerpt': results['documents'][0][i],
                **results['metadatas'][0][i],
            }
            for i in range(len(results['ids'][0]))
        ]

    async def async_add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Non-blocking add using a thread to encode and persist."""
        await asyncio.to_thread(
            self.add, step_id, role, artifact_hash, rationale, content_text, metadata
        )

    async def async_search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Non-blocking search wrapper."""
        return await asyncio.to_thread(self.search, query, k, filter_metadata)

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents matching metadata filters."""
        try:
            self.collection.delete(where=filter_metadata)
            logger.info('Deleted documents from ChromaDB matching %s', filter_metadata)
            return 1
        except Exception as e:
            logger.error('Failed to delete from ChromaDB: %s', e)
            return 0

    def delete_by_ids(self, ids: list[str]) -> int:
        """Delete documents by their IDs."""
        try:
            self.collection.delete(ids=ids)
            logger.info('Deleted %s documents from ChromaDB', len(ids))
            return len(ids)
        except Exception as e:
            logger.error('Failed to delete from ChromaDB: %s', e)
            return 0

    def stats(self) -> dict[str, Any]:
        """Return metadata about the local ChromaDB collection."""
        return {
            'backend': 'ChromaDB (Local)',
            'num_documents': self.collection.count(),
            'embedding_dim': self.model.get_sentence_embedding_dimension(),
        }

    @staticmethod
    def _prepare_text(rationale: str | None, content: str) -> str:
        """Prepare combined text for embedding."""
        parts = []
        if rationale:
            parts.append(rationale)
        if content:
            parts.append(content[:2000])
        return '\n'.join(parts)


class SQLiteBM25Backend(VectorBackend):
    """Local SQLite FTS5 backend for BM25 lexical search."""

    def __init__(
        self,
        collection_name: str = 'APP_memory',
        persist_directory: Path | None = None,
    ) -> None:
        if persist_directory is None:
            persist_directory = Path.home() / '.grinta' / 'memory' / 'sqlite'
        persist_directory.mkdir(parents=True, exist_ok=True)
        self.db_path = persist_directory / f'{collection_name}_fts.db'
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
                    step_id UNINDEXED,
                    role UNINDEXED,
                    content,
                    metadata UNINDEXED
                )
            """)

    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        text = self._prepare_text(rationale, content_text)

        doc_metadata = {
            'step_id': step_id,
            'role': role,
            'timestamp': time.time(),
            **(metadata or {}),
        }
        if artifact_hash:
            doc_metadata['artifact_hash'] = artifact_hash

        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM docs WHERE step_id = ?', (step_id,))
            conn.execute(
                'INSERT INTO docs (step_id, role, content, metadata) VALUES (?, ?, ?, ?)',
                (step_id, role, text[:2000], json.dumps(doc_metadata)),
            )

    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        cleaned_query = ''.join(c if c.isalnum() else ' ' for c in query).strip()
        words = [w for w in cleaned_query.split() if w and len(w) > 2]
        if not words:
            return []

        match_query = ' OR '.join(words)

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT step_id, content, metadata, bm25(docs) as score
                    FROM docs
                    WHERE docs MATCH ?
                    ORDER BY score ASC
                    LIMIT ?
                    """,
                    (match_query, k * 2),
                )

                results = []
                for step_id, content, meta_json, score in cursor:
                    meta = {}
                    try:
                        meta = json.loads(meta_json)
                    except Exception:
                        pass

                    if filter_metadata:
                        match = True
                        for fk, fv in filter_metadata.items():
                            if meta.get(fk) != fv:
                                match = False
                                break
                        if not match:
                            continue

                    results.append(
                        {
                            'step_id': step_id,
                            'score': -score,
                            'excerpt': content,
                            **meta,
                        }
                    )

                    if len(results) >= k:
                        break

                return results
        except sqlite3.OperationalError as e:
            logger.warning("SQLite FTS search failed for query '%s': %s", query, e)
            return []

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        return 0

    def delete_by_ids(self, ids: list[str]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                'DELETE FROM docs WHERE step_id = ?', [(i,) for i in ids]
            )
            return cursor.rowcount

    def stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT count(*) FROM docs')
            count = cursor.fetchone()[0]
        return {
            'backend': 'SQLite FTS5 (BM25)',
            'num_documents': count,
        }

    @staticmethod
    def _prepare_text(rationale: str | None, content: str) -> str:
        parts = []
        if rationale:
            parts.append(rationale)
        if content:
            parts.append(content[:2000])
        return '\n'.join(parts)


__all__ = ['ChromaDBBackend', 'SQLiteBM25Backend']
