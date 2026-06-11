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

from backend.persistence.locations import get_active_local_data_root

logger = logging.getLogger(__name__)


def _default_memory_persist_directory(backend_name: str) -> Path:
    """Return the canonical persistent memory directory for the active project."""
    return Path(get_active_local_data_root()) / 'memory' / backend_name


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
    """Local ChromaDB backend for vector storage.

    Uses ChromaDB's bundled ONNX embedding function (``all-MiniLM-L6-v2``)
    via ``onnxruntime``. No PyTorch / sentence-transformers dependency.
    """

    backend_name = 'ChromaDB (Local)'
    # Use FastEmbed BAAI/bge-small-en-v1.5 which is ONNX-based and fast
    _DEFAULT_EMBEDDING_MODEL = 'BAAI/bge-small-en-v1.5'

    def __init__(  # noqa: D417
        self,
        collection_name: str = 'APP_memory',
        persist_directory: Path | None = None,
        *,
        warm_model_in_background: bool = True,
    ) -> None:
        r"""Initialize ChromaDB local vector store.

        Args:
            collection_name: Name of ChromaDB collection
            persist_directory: Directory for persistent storage

        """
        if persist_directory is None:
            persist_directory = _default_memory_persist_directory('chroma')
        persist_directory.mkdir(parents=True, exist_ok=True)

        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:
            raise RuntimeError(
                'Vector memory requires the optional [rag] extra. '
                "Install with: pip install 'grinta-ai[rag]'"
            ) from exc

        self.client = chromadb.PersistentClient(
            path=str(persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )

        # Embedding function — lazy-loaded in a background thread so __init__ is instant.
        self._model_name = os.getenv('EMBEDDING_MODEL', self._DEFAULT_EMBEDDING_MODEL)
        self._model: Any | None = None  # ChromaDB EmbeddingFunction instance
        self._model_lock = threading.Lock()
        self._model_loader_thread: threading.Thread | None = None

        # Load or create collection, handling embedding model changes
        self._collection_name = collection_name
        try:
            self.collection = self.client.get_collection(
                name=collection_name, embedding_function=self._embedding_function()
            )
            stored_model = self.collection.metadata.get('embedding_model', '')
            if stored_model and stored_model != self._model_name:
                logger.info(
                    'Embedding model changed (%s → %s), recreating collection',
                    stored_model,
                    self._model_name,
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

        if warm_model_in_background:
            self.warm_model_in_background()

    def _create_collection(self, name: str) -> Any:
        """Create a new ChromaDB collection with model metadata."""
        collection = self.client.create_collection(
            name=name,
            embedding_function=self._embedding_function(),
            metadata={'hnsw:space': 'cosine', 'embedding_model': self._model_name},
        )
        logger.info('Created new ChromaDB collection')
        return collection

    def _embedding_function(self) -> Any:
        """Return ChromaDB's default ONNX embedding function (cached)."""
        if self._model is None:
            self._load_model()
        return self._model

    def _load_model(self) -> None:
        """Instantiate ChromaDB's bundled ONNX MiniLM EF. Thread-safe."""
        with self._model_lock:
            if self._model is not None:
                return
            logger.info(
                "Loading FastEmbed ONNX embedding model '%s'…", self._model_name
            )
            from chromadb.utils import embedding_functions

            with (
                contextlib.redirect_stderr(io.StringIO()),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self._model = embedding_functions.FastEmbedEmbeddingFunction(  # type: ignore[attr-defined]
                    model_name=self._model_name
                )
            logger.info('Embedding model ready (%s)', self._model_name)

    def warm_model_in_background(self) -> None:
        """Start loading the embedding model in a daemon thread when not already running."""
        if self._model is not None:
            return
        thread = self._model_loader_thread
        if thread is not None and thread.is_alive():
            return
        self._model_loader_thread = threading.Thread(
            target=self._load_model,
            daemon=True,
            name=f'chroma-model-warmup-{self._collection_name}',
        )
        self._model_loader_thread.start()

    @property
    def model(self) -> Any:
        """Lazy-loaded embedding function. Blocks on first access if still loading."""
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
        """Insert a new document with parent-child chunking into ChromaDB."""
        text = self._prepare_text(rationale, content_text)
        # Ensure EF is loaded
        _ = self.model

        doc_metadata = {
            'step_id': step_id,
            'role': role,
            'timestamp': time.time(),
            'is_child': False,
            **(metadata or {}),
        }
        if artifact_hash:
            doc_metadata['artifact_hash'] = artifact_hash

        # 1. Add the parent document (full context)
        self.collection.add(
            ids=[step_id],
            documents=[text[:2000]],
            metadatas=[doc_metadata],
        )

        # 2. Add child chunks if the text is long enough to benefit
        if len(text) > 600:
            chunk_size = 400
            overlap = 100
            chunks: list[str] = []
            chunk_metadatas = []
            chunk_ids = []

            for i in range(0, len(text), chunk_size - overlap):
                chunk = text[i : i + chunk_size]
                if len(chunk) < 100 and chunks:  # Skip tiny trailing chunks
                    continue
                chunks.append(chunk)
                chunk_metadatas.append(
                    {**doc_metadata, 'is_child': True, 'parent_id': step_id}
                )
                chunk_ids.append(f'{step_id}_child_{len(chunks)}')

                if i + chunk_size >= len(text):
                    break

            if chunks:
                self.collection.add(
                    ids=chunk_ids,
                    documents=chunks,
                    metadatas=chunk_metadatas,  # type: ignore[arg-type]
                )

    def add_batch(
        self,
        step_ids: list[str],
        roles: list[str],
        artifact_hashes: list[str | None],
        rationales: list[str | None],
        content_texts: list[str],
        metadatas: list[dict[str, Any] | None] | None = None,
    ) -> None:
        """Batch insert documents with parent-child chunking into ChromaDB.

        Uses a single collection.add() call for all parents and another for
        all children, drastically reducing embedding+I/O round trips.
        """
        if not step_ids:
            return
        # Ensure embedding model is loaded
        _ = self.model

        all_ids: list[str] = []
        all_docs: list[str] = []
        all_metas: list[dict[str, Any]] = []

        child_ids: list[str] = []
        child_docs: list[str] = []
        child_metas: list[dict[str, Any]] = []

        for idx, step_id in enumerate(step_ids):
            text = self._prepare_text(rationales[idx], content_texts[idx])
            doc_metadata: dict[str, Any] = {
                'step_id': step_id,
                'role': roles[idx],
                'timestamp': time.time(),
                'is_child': False,
                **(metadatas[idx] or {}),  # type: ignore[index]
            }
            if artifact_hashes[idx]:
                doc_metadata['artifact_hash'] = artifact_hashes[idx]

            all_ids.append(step_id)
            all_docs.append(text[:2000])
            all_metas.append(doc_metadata)

            # Generate child chunks
            if len(text) > 600:
                chunk_size = 400
                overlap = 100
                child_count = 0

                for i in range(0, len(text), chunk_size - overlap):
                    chunk = text[i : i + chunk_size]
                    if (
                        len(chunk) < 100
                        and child_ids
                        and child_ids[-1].startswith(f'{step_id}_child_')
                    ):
                        continue
                    child_count += 1
                    child_ids.append(f'{step_id}_child_{child_count}')
                    child_docs.append(chunk)
                    child_metas.append(
                        {**doc_metadata, 'is_child': True, 'parent_id': step_id}
                    )

                    if i + chunk_size >= len(text):
                        break

        # Single batch insert for all parents
        if all_ids:
            self.collection.add(ids=all_ids, documents=all_docs, metadatas=all_metas)  # type: ignore[arg-type]

        # Single batch insert for all children
        if child_ids:
            self.collection.add(
                ids=child_ids,
                documents=child_docs,
                metadatas=child_metas,  # type: ignore[arg-type]
            )

    @staticmethod
    def _build_search_filter(filter_metadata):
        search_filter = {'is_child': True}
        if filter_metadata:
            search_filter.update(filter_metadata)
        return search_filter

    @staticmethod
    def _build_parent_filter(filter_metadata):
        parent_filter = {'is_child': False}
        if filter_metadata:
            parent_filter.update(filter_metadata)
        return parent_filter

    @staticmethod
    def _has_results(results):
        return bool(results['ids'] and results['ids'][0])

    def _query_children(self, query, k, search_filter):
        n_results = min(k * 3, self.collection.count())
        return self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=search_filter,
            include=['documents', 'metadatas', 'distances'],
        )

    def _query_parents(self, query, k, parent_filter):
        return self.collection.query(
            query_texts=[query],
            n_results=min(k, self.collection.count()),
            where=parent_filter,
            include=['documents', 'metadatas', 'distances'],
        )

    def _query_with_fallback(self, query, k, search_filter, filter_metadata):
        results = self._query_children(query, k, search_filter)
        if self._has_results(results):
            return results
        parent_filter = self._build_parent_filter(filter_metadata)
        results = self._query_parents(query, k, parent_filter)
        if self._has_results(results):
            return results
        return None

    @staticmethod
    def _process_single_match(
        pid, meta, dist, doc, parent_ids, scores, parent_texts, parent_metas
    ):
        score = 1.0 - dist
        if pid not in scores:
            parent_ids.append(pid)
            scores[pid] = score
            if meta.get('is_child') is False:
                parent_texts[pid] = doc
                parent_metas[pid] = meta
            else:
                parent_metas[pid] = {k: v for k, v in meta.items() if k != 'parent_id'}
                parent_metas[pid].pop('is_child', None)
        else:
            scores[pid] = max(scores[pid], score)

    def _resolve_parent_matches(self, results):
        parent_ids = []
        scores = {}
        parent_texts = {}
        parent_metas = {}

        ids_list = results['ids'][0]
        metas_list = results['metadatas'][0]
        dists_list = results['distances'][0]
        docs_list = results['documents'][0]

        for i, meta in enumerate(metas_list):
            pid = meta.get('parent_id') or ids_list[i]
            self._process_single_match(
                pid,
                meta,
                dists_list[i],
                docs_list[i],
                parent_ids,
                scores,
                parent_texts,
                parent_metas,
            )

        return parent_ids, scores, parent_texts, parent_metas

    def _fetch_missing_parents(self, parent_ids, k, parent_texts, parent_metas):
        needed_ids = [pid for pid in parent_ids[:k] if pid not in parent_texts]
        if not needed_ids:
            return
        parent_results = self.collection.get(
            ids=needed_ids,
            include=['documents', 'metadatas'],
        )
        for i, pid in enumerate(parent_results['ids']):
            parent_texts[pid] = parent_results['documents'][i]
            parent_metas[pid] = dict(parent_results['metadatas'][i])

    def _assemble_and_sort(self, parent_ids, k, scores, parent_texts, parent_metas):
        final_results = []
        for pid in parent_ids[:k]:
            final_results.append(
                {
                    'step_id': pid,
                    'score': scores.get(pid, 0.0),
                    'excerpt': parent_texts.get(pid, ''),
                    **parent_metas.get(pid, {}),
                }
            )
        final_results.sort(key=lambda x: x['score'], reverse=True)
        return final_results[:k]

    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search child chunks and return their parent documents for context.

        Uses a single query() call that includes documents, then resolves
        parent texts from the same result set when possible, falling back
        to a .get() only for parents whose text was not already returned.
        """
        if self.collection.count() == 0:
            return []

        _ = self.model

        search_filter = self._build_search_filter(filter_metadata)
        results = self._query_with_fallback(query, k, search_filter, filter_metadata)
        if results is None:
            return []

        parent_ids, scores, parent_texts, parent_metas = self._resolve_parent_matches(
            results
        )
        self._fetch_missing_parents(parent_ids, k, parent_texts, parent_metas)
        return self._assemble_and_sort(
            parent_ids, k, scores, parent_texts, parent_metas
        )

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
        """Return metadata about the local ChromaDB collection without forcing model load."""
        stats: dict[str, Any] = {
            'backend': self.backend_name,
            'num_documents': self.collection.count(),
            'embedding_model': self._model_name,
            'model_loaded': self._model is not None,
        }
        if self._model is not None:
            # Chroma's bundled MiniLM-L6 emits 384-dim vectors.
            stats['embedding_dim'] = 384
        return stats

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
            persist_directory = _default_memory_persist_directory('sqlite')
        persist_directory.mkdir(parents=True, exist_ok=True)
        self.db_path = persist_directory / f'{collection_name}_fts.db'
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a per-thread persistent SQLite connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            self._local.conn = conn
        return self._local.conn

    def _close_conn(self) -> None:
        """Close the per-thread connection if open."""
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
                step_id UNINDEXED,
                role UNINDEXED,
                content,
                metadata UNINDEXED
            )
        """)
        conn.commit()

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

        conn = self._get_conn()
        conn.execute(
            'INSERT OR REPLACE INTO docs (step_id, role, content, metadata) VALUES (?, ?, ?, ?)',
            (step_id, role, text[:2000], json.dumps(doc_metadata)),
        )
        conn.commit()

    def add_batch(
        self,
        step_ids: list[str],
        roles: list[str],
        artifact_hashes: list[str | None],
        rationales: list[str | None],
        content_texts: list[str],
        metadatas: list[dict[str, Any] | None] | None = None,
    ) -> None:
        """Batch insert documents using a single transaction.

        Uses INSERT OR REPLACE for upsert semantics in one round trip.
        """
        if not step_ids:
            return
        if metadatas is None:
            metadatas = [None] * len(step_ids)

        conn = self._get_conn()
        rows = []
        for idx, step_id in enumerate(step_ids):
            text = self._prepare_text(rationales[idx], content_texts[idx])
            doc_metadata = {
                'step_id': step_id,
                'role': roles[idx],
                'timestamp': time.time(),
                **(metadatas[idx] or {}),
            }
            if artifact_hashes[idx]:
                doc_metadata['artifact_hash'] = artifact_hashes[idx]
            rows.append((step_id, roles[idx], text[:2000], json.dumps(doc_metadata)))

        conn.executemany(
            'INSERT OR REPLACE INTO docs (step_id, role, content, metadata) VALUES (?, ?, ?, ?)',
            rows,
        )
        conn.commit()

    @staticmethod
    def _metadata_matches_filter(
        meta: dict[str, Any], filter_metadata: dict[str, Any]
    ) -> bool:
        return all(meta.get(fk) == fv for fk, fv in filter_metadata.items())

    @staticmethod
    def _load_row_metadata(meta_json: str) -> dict[str, Any]:
        try:
            loaded = json.loads(meta_json)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _append_fts_row(
        self,
        results: list[dict[str, Any]],
        *,
        step_id: str,
        content: str,
        meta_json: str,
        score: float,
        filter_metadata: dict[str, Any] | None,
        k: int,
    ) -> bool:
        meta = self._load_row_metadata(meta_json)
        if filter_metadata and not self._metadata_matches_filter(meta, filter_metadata):
            return False
        results.append(
            {
                'step_id': step_id,
                'score': -score,
                'excerpt': content,
                **meta,
            }
        )
        return len(results) >= k

    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        cleaned_query = ''.join(c if c.isalnum() else ' ' for c in query).strip()
        words = [w for w in cleaned_query.split() if w and len(w) > 2]
        if not words:
            return []

        match_query = ' OR '.join(words)

        try:
            conn = self._get_conn()
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

            results: list[dict[str, Any]] = []
            for step_id, content, meta_json, score in cursor:
                if self._append_fts_row(
                    results,
                    step_id=step_id,
                    content=content,
                    meta_json=meta_json,
                    score=score,
                    filter_metadata=filter_metadata,
                    k=k,
                ):
                    break

            return results
        except sqlite3.OperationalError as e:
            logger.warning("SQLite FTS search failed for query '%s': %s", query, e)
            return []

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents whose stored metadata matches all filter criteria."""
        if not filter_metadata:
            return 0

        conn = self._get_conn()
        # Fetch all rows and filter by metadata JSON (FTS5 doesn't index arbitrary
        # JSON fields, so we must scan and match in Python).
        cursor = conn.execute('SELECT rowid, metadata FROM docs')
        ids_to_delete: list[int] = []
        for rowid, meta_json in cursor:
            meta = self._load_row_metadata(meta_json)
            if self._metadata_matches_filter(meta, filter_metadata):
                ids_to_delete.append(rowid)

        if not ids_to_delete:
            return 0

        conn.executemany(
            'DELETE FROM docs WHERE rowid = ?', [(rid,) for rid in ids_to_delete]
        )
        conn.commit()
        return len(ids_to_delete)

    def delete_by_ids(self, ids: list[str]) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.executemany('DELETE FROM docs WHERE step_id = ?', [(i,) for i in ids])
        conn.commit()
        return cursor.rowcount

    def stats(self) -> dict[str, Any]:
        conn = self._get_conn()
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
