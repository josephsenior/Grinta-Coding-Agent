"""Enhanced local vector store: hybrid (semantic + BM25) search with LRU cache.

Features:
- ChromaDB (ONNX MiniLM) semantic backend
- SQLite FTS5 BM25 lexical backend
- LRU query cache with TTL

Requires the optional ``[rag]`` extra (``pip install 'grinta-ai[rag]'``).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import itertools
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

_LOCAL_VECTOR_STORE = importlib.import_module(
    __name__.rsplit('.', 1)[0] + '._local_vector_store'
)
SQLiteBM25Backend = _LOCAL_VECTOR_STORE.SQLiteBM25Backend

logger = logging.getLogger(__name__)


class QueryCache:
    """LRU cache for query results with TTL."""

    def __init__(self, max_size: int = 10000, ttl: int = 3600) -> None:
        """Initialize the cache with maximum size and expiration period in seconds."""
        self.cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.hits = 0
        self.misses = 0

    def get(self, query: str) -> list[dict[str, Any]] | None:
        """Get cached results if not expired."""
        cache_key = self._hash_query(query)
        if cache_key in self.cache:
            timestamp, results = self.cache[cache_key]
            if time.time() - timestamp < self.ttl:
                # Move to end (most recently used)
                self.cache.move_to_end(cache_key)
                self.hits += 1
                logger.debug('Cache HIT for query: %s', query[:50])
                return results
            # Expired, remove
            del self.cache[cache_key]

        self.misses += 1
        logger.debug('Cache MISS for query: %s', query[:50])
        return None

    def store(self, query: str, results: list[dict[str, Any]]) -> None:
        """Cache query results."""
        cache_key = self._hash_query(query)
        self.cache[cache_key] = (time.time(), results)

        # Evict oldest if over max size
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def invalidate_by_step_ids(self, step_ids: set[str]) -> int:
        """Remove cache entries whose results contain any of the given step_ids.

        Returns the number of entries evicted.
        """
        evicted = 0
        keys_to_remove: list[str] = []
        for key, (_, results) in self.cache.items():
            if any(r.get('step_id') in step_ids for r in results):
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self.cache[key]
            evicted += 1
        return evicted

    def invalidate_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Remove cache entries whose results contain documents matching all filter criteria.

        Returns the number of entries evicted.
        """
        evicted = 0
        keys_to_remove: list[str] = []
        for key, (_, results) in self.cache.items():
            for r in results:
                if all(r.get(k) == v for k, v in filter_metadata.items()):
                    keys_to_remove.append(key)
                    break
        for key in keys_to_remove:
            del self.cache[key]
            evicted += 1
        return evicted

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'size': len(self.cache),
            'max_size': self.max_size,
        }

    @staticmethod
    def _hash_query(query: str) -> str:
        """Generate cache key from query."""
        return hashlib.sha256(query.encode()).hexdigest()[:16]


class EnhancedVectorStore:
    """Hybrid (semantic + BM25) local vector store with LRU query cache.

    Re-ranking with a cross-encoder was removed in 0.56 to drop the
    sentence-transformers / torch dependency from the install footprint.
    Top-k results come from BM25 + ANN deduplication.
    """

    def __init__(  # noqa: D417
        self,
        collection_name: str = 'APP_memory',
        backend_type: str | None = None,
        enable_cache: bool = True,
        enable_reranking: bool = True,
        cache_size: int = 10000,
        cache_ttl: int = 3600,
        warm_embeddings_in_background: bool = True,
    ) -> None:
        """Initialize enhanced vector store.

        Args:
            collection_name: Name of the collection
            backend_type: Force backend ("chromadb", "qdrant", or None for auto)
            enable_cache: Enable query caching
            enable_reranking: Deprecated; ignored. Reranker was removed in 0.56.
            cache_size: Maximum cache entries
            cache_ttl: Cache TTL in seconds

        """
        chroma_backend_cls = _LOCAL_VECTOR_STORE.ChromaDBBackend

        self.backend: Any = chroma_backend_cls(
            collection_name,
            warm_model_in_background=warm_embeddings_in_background,
        )
        self.bm25_backend = SQLiteBM25Backend(collection_name)

        # Initialize cache
        self.cache: QueryCache | None = (
            QueryCache(max_size=cache_size, ttl=cache_ttl) if enable_cache else None
        )

        self.enable_reranking = enable_reranking
        if self.enable_reranking:
            try:
                import os

                from flashrank import Ranker

                cache_dir = _LOCAL_VECTOR_STORE._default_memory_persist_directory(
                    'flashrank'
                )
                os.makedirs(cache_dir, exist_ok=True)
                # tinybert is very fast and lightweight
                self.reranker = Ranker(
                    model_name='ms-marco-TinyBERT-L-2-v2', cache_dir=str(cache_dir)
                )
            except ImportError:
                logger.warning('flashrank not installed, falling back to no reranking')
                self.reranker = None
        else:
            self.reranker = None

        # Configuration
        self.config: dict[str, bool | int | float] = {
            'caching_enabled': enable_cache,
            'initial_k': 20,
            'final_k': 5,
        }

        logger.info(
            'Initialized EnhancedVectorStore\n  Backend: %s\n  Cache: %s',
            getattr(self.backend, 'backend_name', type(self.backend).__name__),
            'enabled' if enable_cache else 'disabled',
        )

    def start_background_warmup(self) -> None:
        """Kick off any optional backend warmup without blocking startup."""
        starter = getattr(self.backend, 'warm_model_in_background', None)
        if callable(starter):
            starter()

    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a document to both backends."""
        self.backend.add(
            step_id, role, artifact_hash, rationale, content_text, metadata
        )
        self.bm25_backend.add(
            step_id, role, artifact_hash, rationale, content_text, metadata
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
        """Add multiple documents to both backends in a single batch call."""
        self.backend.add_batch(
            step_ids, roles, artifact_hashes, rationales, content_texts, metadatas
        )
        self.bm25_backend.add_batch(
            step_ids, roles, artifact_hashes, rationales, content_texts, metadatas
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
        """Async wrapper to add a document without blocking the event loop.

        Offloads potentially CPU and I/O heavy operations to a worker thread.
        """
        await asyncio.to_thread(
            self.add, step_id, role, artifact_hash, rationale, content_text, metadata
        )

    async def async_add_batch(
        self,
        step_ids: list[str],
        roles: list[str],
        artifact_hashes: list[str | None],
        rationales: list[str | None],
        content_texts: list[str],
        metadatas: list[dict[str, Any] | None] | None = None,
    ) -> None:
        """Async batch add to avoid blocking the event loop."""
        await asyncio.to_thread(
            self.add_batch,
            step_ids,
            roles,
            artifact_hashes,
            rationales,
            content_texts,
            metadatas,
        )

    def _effective_initial_k(self, k: int) -> int:
        initial_k_raw = self.config.get('initial_k', 20)
        if isinstance(initial_k_raw, bool):
            initial_k_raw = 20
        elif not isinstance(initial_k_raw, int):
            initial_k_raw = int(initial_k_raw)
        return max(initial_k_raw, k * 2)

    @staticmethod
    def _dedupe_candidates_by_step_id(
        semantic_candidates: list[dict[str, Any]],
        lexical_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen_ids: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for doc in itertools.chain(semantic_candidates, lexical_candidates):
            step_id = doc['step_id']
            if step_id in seen_ids:
                continue
            seen_ids.add(step_id)
            candidates.append(doc)
        return candidates

    def _finalize_hybrid_results(
        self,
        query: str,
        k: int,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self.reranker or not candidates:
            return candidates[:k]

        try:
            from flashrank import RerankRequest

            passages = [
                {
                    'id': c.get('step_id', str(i)),
                    'text': c.get('excerpt', ''),
                }
                for i, c in enumerate(candidates)
            ]

            rerank_request = RerankRequest(query=query, passages=passages)
            results = self.reranker.rerank(rerank_request)

            # Map back to original candidate dicts
            candidates_by_id = {c.get('step_id'): c for c in candidates}
            reranked_candidates = []
            for r in results:
                original = candidates_by_id.get(r.get('id'))
                if original:
                    new_candidate = dict(original)
                    new_candidate['score'] = r.get('score', new_candidate['score'])
                    reranked_candidates.append(new_candidate)

            # If some candidates were dropped by the reranker (shouldn't happen), append them
            returned_ids = {r.get('id') for r in results}
            for c in candidates:
                if c.get('step_id') not in returned_ids:
                    reranked_candidates.append(c)

            return reranked_candidates[:k]

        except Exception as e:
            logger.warning(
                'FlashRank reranking failed, falling back to original order: %s', e
            )
            return candidates[:k]

    def _try_cached_search(
        self,
        query: str,
        k: int,
        filter_metadata: dict[str, Any] | None,
        start_time: float,
    ) -> list[dict[str, Any]] | None:
        if not self.cache:
            return None
        cached_results = self.cache.get(query)
        if cached_results is None:
            return None
        filtered_results = self._apply_filters(cached_results, k, filter_metadata)
        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug('Cache hit! Returned in %.1fms', elapsed_ms)
        return filtered_results

    def _search_backends_in_parallel(
        self, query: str, initial_k: int, filter_metadata: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Run semantic and BM25 searches concurrently and return both result sets."""
        semantic_candidates: list[dict[str, Any]] = []
        lexical_candidates: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            sem_future = pool.submit(
                self.backend.search, query, k=initial_k, filter_metadata=filter_metadata
            )
            lex_future = pool.submit(
                self.bm25_backend.search,
                query,
                k=initial_k,
                filter_metadata=filter_metadata,
            )
            for future in as_completed([sem_future, lex_future]):
                try:
                    result = future.result()
                    if future is sem_future:
                        semantic_candidates = result
                    else:
                        lexical_candidates = result
                except Exception:
                    # If one backend fails, fall back to the other
                    logger.warning(
                        'One backend failed during parallel search', exc_info=True
                    )
                    if future is sem_future:
                        semantic_candidates = []
                    else:
                        lexical_candidates = []

        return semantic_candidates, lexical_candidates

    def search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search with caching and re-ranking for maximum accuracy.

        Process:
        1. Check cache (if enabled)
        2. Vector search with higher k (20 vs 5) — both backends run in parallel
        3. Re-rank with cross-encoder (if enabled)
        4. Return top k results
        5. Cache for future queries

        Args:
            query: Search query
            k: Number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of top k results with high accuracy

        """
        start_time = time.time()

        cached = self._try_cached_search(query, k, filter_metadata, start_time)
        if cached is not None:
            return cached

        initial_k = self._effective_initial_k(k)
        semantic_candidates, lexical_candidates = self._search_backends_in_parallel(
            query, initial_k, filter_metadata
        )

        candidates = self._dedupe_candidates_by_step_id(
            semantic_candidates, lexical_candidates
        )

        if not candidates:
            return []

        results = self._finalize_hybrid_results(query, k, candidates)

        # Cache the results
        if self.cache:
            self.cache.store(query, results)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug(
            'Search completed in %.1fms (retrieved %s, re-ranked to %s)',
            elapsed_ms,
            len(candidates),
            len(results),
        )

        return results

    async def async_search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Async wrapper for search to avoid blocking the event loop.

        Executes the synchronous search in a thread, preserving existing logic
        including caching and optional re-ranking.
        """
        return await asyncio.to_thread(self.search, query, k, filter_metadata)

    def _delete_backends_in_parallel(
        self,
        delete_fn_semantic: Any,
        delete_fn_lexical: Any,
        *args: Any,
    ) -> int:
        """Run delete operations on both backends concurrently."""
        c1: int = 0
        c2: int = 0
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(delete_fn_semantic, *args)
            f2 = pool.submit(delete_fn_lexical, *args)
            try:
                c1 = f1.result()
            except Exception:
                logger.warning('Semantic backend delete failed', exc_info=True)
            try:
                c2 = f2.result()
            except Exception:
                logger.warning('BM25 backend delete failed', exc_info=True)
        return max(c1, c2)

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents matching metadata filters.

        Also selectively invalidates cache entries that reference deleted documents.
        """
        deleted_count = self._delete_backends_in_parallel(
            self.backend.delete_by_metadata,
            self.bm25_backend.delete_by_metadata,
            filter_metadata,
        )

        # Selectively invalidate cache entries matching the deleted metadata
        if self.cache:
            evicted = self.cache.invalidate_by_metadata(filter_metadata)
            logger.debug(
                'Invalidated %s cache entries after metadata-based deletion', evicted
            )

        return deleted_count

    def delete_by_ids(self, ids: list[str]) -> int:
        """Delete documents by their IDs.

        Also selectively invalidates cache entries that reference deleted documents.
        """
        deleted_count = self._delete_backends_in_parallel(
            self.backend.delete_by_ids,
            self.bm25_backend.delete_by_ids,
            ids,
        )

        # Selectively invalidate cache entries referencing deleted step_ids
        if self.cache:
            evicted = self.cache.invalidate_by_step_ids(set(ids))
            logger.debug(
                'Invalidated %s cache entries after ID-based deletion', evicted
            )

        return deleted_count

    def stats(self) -> dict[str, Any]:
        """Get comprehensive statistics."""
        backend_stats = self.backend.stats()

        stats = {
            **backend_stats,
            'config': self.config,
        }

        if self.cache:
            stats['cache'] = self.cache.stats()

        return stats

    @staticmethod
    def _apply_filters(
        results: list[dict[str, Any]],
        k: int,
        filter_metadata: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Apply post-filtering to cached results.

        Filters cached search results based on metadata criteria and returns top k items.
        Used after cache hits to apply dynamic filtering without re-running expensive
        vector search operations.

        Args:
            results: List of cached search results to filter
            k: Maximum number of results to return
            filter_metadata: Optional dict of metadata key-value pairs for filtering.
                All pairs must match for a result to be included. Example:
                {"role": "user", "step_id": "step_123"}

        Returns:
            list[dict[str, Any]]: Filtered results limited to k items. If no filters
                specified, returns first k results. If filters specified, returns up to
                k results that match all filter criteria.

        Example:
            >>> results = [
            ...     {"step_id": "1", "role": "user", "score": 0.9},
            ...     {"step_id": "2", "role": "assistant", "score": 0.85},
            ... ]
            >>> filtered = EnhancedVectorStore._apply_filters(
            ...     results, k=1, filter_metadata={"role": "user"}
            ... )
            >>> len(filtered)
            1
            >>> filtered[0]["role"]
            "user"

        """
        if filter_metadata:
            filtered = [
                r
                for r in results
                if all(r.get(key) == value for key, value in filter_metadata.items())
            ]
            return filtered[:k]
        return results[:k]


__all__ = [
    'EnhancedVectorStore',
    'QueryCache',
]
