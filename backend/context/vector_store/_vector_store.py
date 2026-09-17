"""History search store: SQLite FTS5 (BM25) keyword search with an LRU query cache.

This is what backs ``search_history``. It depends only on the standard
library's ``sqlite3`` (FTS5), so it is available on every install.

It used to be a hybrid store that also ran a ChromaDB/fastembed semantic
backend and optional flashrank re-ranking behind a ``[rag]`` extra. That stack
was removed: agent history queries are dominated by identifiers, file paths
and error strings, where keyword matching is strong, while the embedding stack
cost a heavy install and first-run model downloads, and left ``search_history``
unavailable on the base install.

The storage backend is pluggable: pass any :class:`VectorBackend` as
``backend=`` to experiment with a different retrieval strategy (for example a
semantic one) without changing callers.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

_LOCAL_VECTOR_STORE = importlib.import_module(
    __name__.rsplit('.', 1)[0] + '._local_vector_store'
)
SQLiteBM25Backend = _LOCAL_VECTOR_STORE.SQLiteBM25Backend

logger = logging.getLogger(__name__)

# Metadata key used to scope stored documents to a session/tenant.
# All search() calls (or callers like ContextTracker) should add a filter
# so cross-session data cannot leak.
TENANT_METADATA_KEY = 'session_id'


def _resolve_current_tenant() -> str | None:
    """Return the active session id from the session context, if any."""
    try:
        from backend.context.memory.session_context import (
            bind_session_context,
        )
        from backend.engine.tools.working_memory import get_current_session_id

        bind_session_context()
        sid = get_current_session_id()
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    except Exception:
        return None
    return None


class QueryCache:
    """LRU cache for query results with TTL.

    Cache keys are derived from the **query, tenant (session_id), and any
    filter metadata** so two sessions searching the same text cannot
    observe each other's cached results.
    """

    def __init__(self, max_size: int = 10000, ttl: int = 3600) -> None:
        """Initialize the cache with maximum size and expiration period in seconds."""
        self.cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def get(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Get cached results if not expired.

        Backwards compatible: if no tenant/filter is supplied, the cache
        degrades to a query-only key (the previous behavior). New code
        should always pass a tenant_id.
        """
        cache_key = self._hash_query(
            query, tenant_id=tenant_id, filter_metadata=filter_metadata
        )
        with self._lock:
            entry = self.cache.get(cache_key)
            if entry is None:
                self.misses += 1
                logger.debug('Cache MISS for query: %s', query[:50])
                return None
            timestamp, results = entry
            if time.time() - timestamp < self.ttl:
                # Move to end (most recently used) under the lock to keep
                # the OrderedDict consistent under concurrent access.
                self.cache.move_to_end(cache_key)
                self.hits += 1
                logger.debug('Cache HIT for query: %s', query[:50])
                return results
            # Expired
            del self.cache[cache_key]
            self.misses += 1
            logger.debug('Cache MISS (expired) for query: %s', query[:50])
            return None

    def store(
        self,
        query: str,
        results: list[dict[str, Any]],
        *,
        tenant_id: str | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Cache query results."""
        cache_key = self._hash_query(
            query, tenant_id=tenant_id, filter_metadata=filter_metadata
        )
        with self._lock:
            self.cache[cache_key] = (time.time(), results)
            # LRU eviction — never full-clear (avoids thundering herd).
            while len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def invalidate_by_step_ids(self, step_ids: set[str]) -> int:
        """Remove cache entries whose results contain any of the given step_ids.

        Returns the number of entries evicted.
        """
        evicted = 0
        with self._lock:
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
        with self._lock:
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

    def clear(self) -> None:
        """Drop every cached entry (e.g. on session end)."""
        with self._lock:
            self.cache.clear()

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
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
    def _hash_query(
        query: str,
        *,
        tenant_id: str | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate a tenant+filter+query cache key.

        The tenant is always part of the key. When callers omit the tenant
        explicitly we still namespace their key under ``__no_tenant__`` so
        it can never collide with a future tenant-scoped lookup.
        """
        tenant = tenant_id or '__no_tenant__'
        filter_sig = ''
        if filter_metadata:
            try:
                filter_sig = json.dumps(filter_metadata, sort_keys=True, default=str)
            except Exception:
                filter_sig = repr(filter_metadata)
        payload = f'{tenant}\x00{query}\x00{filter_sig}'
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


class EnhancedVectorStore:
    """History search store: one pluggable backend plus an LRU query cache.

    Defaults to :class:`SQLiteBM25Backend` (SQLite FTS5 keyword search, no
    third-party dependencies). The class name is kept for API stability.

    Multi-tenant isolation: callers MUST pass ``tenant_id`` (typically the
    session id) to :meth:`add` and :meth:`search` so documents and cached
    results cannot leak across sessions. The ``filter_metadata`` argument
    on :meth:`search` is automatically extended with the tenant key when
    a tenant id is provided.
    """

    def __init__(
        self,
        collection_name: str = 'APP_memory',
        *,
        backend: Any | None = None,
        enable_cache: bool = True,
        cache_size: int = 10000,
        cache_ttl: int = 3600,
    ) -> None:
        """Initialize the store.

        Args:
            collection_name: Name of the collection (the SQLite table namespace).
            backend: Optional :class:`VectorBackend` to use instead of the
                default SQLite FTS5 keyword backend.
            enable_cache: Enable query caching.
            cache_size: Maximum cache entries.
            cache_ttl: Cache TTL in seconds.
        """
        self.backend: Any = (
            backend if backend is not None else SQLiteBM25Backend(collection_name)
        )

        self.cache: QueryCache | None = (
            QueryCache(max_size=cache_size, ttl=cache_ttl) if enable_cache else None
        )

        self.config: dict[str, bool | int | float] = {
            'caching_enabled': enable_cache,
            'final_k': 5,
        }

        logger.info(
            'Initialized history search store (backend: %s, cache: %s)',
            getattr(self.backend, 'backend_name', type(self.backend).__name__),
            'enabled' if enable_cache else 'disabled',
        )

    @staticmethod
    def _attach_tenant_metadata(
        metadata: dict[str, Any] | None,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        """Return a copy of *metadata* with the tenant key stamped in.

        Existing tenant keys (e.g. set explicitly) are not overwritten.
        """
        merged: dict[str, Any] = dict(metadata or {})
        if tenant_id and TENANT_METADATA_KEY not in merged:
            merged[TENANT_METADATA_KEY] = tenant_id
        return merged

    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Add a document.

        The tenant (session) id is stamped into the document metadata so
        future :meth:`search` calls with the same tenant can filter on it.
        """
        merged = self._attach_tenant_metadata(metadata, tenant_id)
        self.backend.add(step_id, role, artifact_hash, rationale, content_text, merged)

    def add_batch(
        self,
        step_ids: list[str],
        roles: list[str],
        artifact_hashes: list[str | None],
        rationales: list[str | None],
        content_texts: list[str],
        metadatas: list[dict[str, Any] | None] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Add multiple documents in a single batch call.

        All batched documents share the same *tenant_id*; the value is
        stamped into each document's metadata.
        """
        if metadatas is None:
            metadatas = [None] * len(step_ids)
        merged_metas: list[dict[str, Any] | None] = [
            self._attach_tenant_metadata(meta, tenant_id) for meta in metadatas
        ]
        self.backend.add_batch(
            step_ids, roles, artifact_hashes, rationales, content_texts, merged_metas
        )

    async def async_add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Async wrapper to add a document without blocking the event loop."""
        await asyncio.to_thread(
            self.add,
            step_id,
            role,
            artifact_hash,
            rationale,
            content_text,
            metadata,
            tenant_id=tenant_id,
        )

    async def async_add_batch(
        self,
        step_ids: list[str],
        roles: list[str],
        artifact_hashes: list[str | None],
        rationales: list[str | None],
        content_texts: list[str],
        metadatas: list[dict[str, Any] | None] | None = None,
        *,
        tenant_id: str | None = None,
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
            tenant_id=tenant_id,
        )

    def _try_cached_search(
        self,
        query: str,
        k: int,
        filter_metadata: dict[str, Any] | None,
        start_time: float,
        *,
        tenant_id: str | None,
    ) -> list[dict[str, Any]] | None:
        if not self.cache:
            return None
        cached_results = self.cache.get(
            query, tenant_id=tenant_id, filter_metadata=filter_metadata
        )
        if cached_results is None:
            return None
        filtered_results = self._apply_filters(
            cached_results, k, filter_metadata, tenant_id=tenant_id
        )
        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug('Cache hit! Returned in %.1fms', elapsed_ms)
        return filtered_results

    def search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search stored history.

        Process:
        1. Check cache (if enabled), scoped by *tenant_id* and filter
        2. Query the backend with the tenant folded into the filter
        3. Re-apply the tenant filter in Python, defending against a backend
           that ignores the filter
        4. Cache and return the top k results

        Args:
            query: Search query
            k: Number of results to return
            filter_metadata: Optional metadata filters (merged with tenant)
            tenant_id: Optional tenant (session) id. When provided, the
                search is restricted to documents written with the same
                tenant. Defaults to the currently bound session id, if any.

        Returns:
            List of up to k results, best match first.
        """
        if tenant_id is None:
            tenant_id = _resolve_current_tenant()

        start_time = time.time()

        cached = self._try_cached_search(
            query, k, filter_metadata, start_time, tenant_id=tenant_id
        )
        if cached is not None:
            return cached

        merged_filter = self._attach_tenant_metadata(filter_metadata, tenant_id)
        try:
            candidates = self.backend.search(query, k=k, filter_metadata=merged_filter)
        except Exception:
            logger.warning('History search backend failed', exc_info=True)
            return []

        if tenant_id:
            candidates = [
                c
                for c in candidates
                if c.get(TENANT_METADATA_KEY) is None
                or c.get(TENANT_METADATA_KEY) == tenant_id
            ]

        results = candidates[:k]
        if not results:
            return []

        if self.cache:
            self.cache.store(
                query, results, tenant_id=tenant_id, filter_metadata=filter_metadata
            )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug(
            'Search completed in %.1fms (%s results)', elapsed_ms, len(results)
        )
        return results

    async def async_search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Async wrapper for search to avoid blocking the event loop."""
        return await asyncio.to_thread(
            self.search, query, k, filter_metadata, tenant_id=tenant_id
        )

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents matching metadata filters.

        Also selectively invalidates cache entries that reference deleted documents.
        """
        deleted_count = self.backend.delete_by_metadata(filter_metadata)
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
        deleted_count = self.backend.delete_by_ids(ids)
        if self.cache:
            evicted = self.cache.invalidate_by_step_ids(set(ids))
            logger.debug(
                'Invalidated %s cache entries after ID-based deletion', evicted
            )
        return deleted_count

    def stats(self) -> dict[str, Any]:
        """Get comprehensive statistics."""
        stats = {
            **self.backend.stats(),
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
        *,
        tenant_id: str | None = None,
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
            tenant_id: Optional tenant key. When supplied, results without
                a matching tenant metadata are dropped (documents without
                tenant metadata are also kept, to support legacy entries).

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
        filtered: list[dict[str, Any]]
        if filter_metadata:
            filtered = [
                r
                for r in results
                if all(r.get(key) == value for key, value in filter_metadata.items())
            ]
        else:
            filtered = list(results)

        if tenant_id is not None:
            filtered = [
                r
                for r in filtered
                if r.get(TENANT_METADATA_KEY) is None
                or r.get(TENANT_METADATA_KEY) == tenant_id
            ]

        return filtered[:k]


__all__ = [
    'EnhancedVectorStore',
    'QueryCache',
]
