"""Tests for backend.context.vector_store — QueryCache."""

from __future__ import annotations

import inspect
import time
from unittest.mock import MagicMock, PropertyMock, patch

from backend.context.vector_store import (
    ChromaDBBackend,
    EnhancedVectorStore,
    QueryCache,
    SQLiteBM25Backend,
)


class TestQueryCacheInit:
    def test_defaults(self):
        cache = QueryCache()
        assert cache.max_size == 10000
        assert cache.ttl == 3600
        assert cache.hits == 0
        assert cache.misses == 0

    def test_custom_params(self):
        cache = QueryCache(max_size=100, ttl=60)
        assert cache.max_size == 100
        assert cache.ttl == 60


class TestQueryCacheGetSet:
    def test_set_and_get(self):
        cache = QueryCache()
        cache.store('hello', [{'id': 1}])
        result = cache.get('hello')
        assert result == [{'id': 1}]
        assert cache.hits == 1
        assert cache.misses == 0

    def test_get_miss(self):
        cache = QueryCache()
        result = cache.get('nonexistent')
        assert result is None
        assert cache.misses == 1

    def test_get_expired(self):
        cache = QueryCache(ttl=0)  # Immediately expires
        cache.store('q', [{'id': 1}])
        # Force expiration by sleeping a tiny bit
        time.sleep(0.01)
        result = cache.get('q')
        assert result is None
        assert cache.misses == 1

    def test_overwrite_existing(self):
        cache = QueryCache()
        cache.store('q', [{'id': 1}])
        cache.store('q', [{'id': 2}])
        result = cache.get('q')
        assert result == [{'id': 2}]

    def test_lru_eviction(self):
        cache = QueryCache(max_size=2)
        cache.store('a', [{'v': 1}])
        cache.store('b', [{'v': 2}])
        cache.store('c', [{'v': 3}])  # Should evict "a"
        assert cache.get('a') is None
        assert cache.get('b') is not None
        assert cache.get('c') is not None

    def test_lru_moves_to_end(self):
        cache = QueryCache(max_size=2)
        cache.store('a', [{'v': 1}])
        cache.store('b', [{'v': 2}])
        # Access "a" to move it to end
        cache.get('a')
        cache.store('c', [{'v': 3}])  # Should evict "b" (least recently used)
        assert cache.get('a') is not None
        assert cache.get('b') is None


class TestQueryCacheStats:
    def test_stats_empty(self):
        cache = QueryCache()
        stats = cache.stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 0
        assert stats['hit_rate'] == 0
        assert stats['size'] == 0

    def test_stats_with_data(self):
        cache = QueryCache()
        cache.store('x', [])
        cache.get('x')  # hit
        cache.get('y')  # miss
        stats = cache.stats()
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert stats['hit_rate'] == 0.5


class TestQueryCacheHashQuery:
    def test_deterministic(self):
        h1 = QueryCache._hash_query('test query')
        h2 = QueryCache._hash_query('test query')
        assert h1 == h2

    def test_different_queries_different_hashes(self):
        h1 = QueryCache._hash_query('query A')
        h2 = QueryCache._hash_query('query B')
        assert h1 != h2

    def test_hash_is_24_chars(self):
        h = QueryCache._hash_query('anything')
        assert len(h) == 24

    def test_tenant_changes_hash(self):
        h_no_tenant = QueryCache._hash_query('q')
        h_tenant_a = QueryCache._hash_query('q', tenant_id='session-a')
        h_tenant_b = QueryCache._hash_query('q', tenant_id='session-b')
        assert h_no_tenant != h_tenant_a
        assert h_tenant_a != h_tenant_b
        assert h_no_tenant != h_tenant_b

    def test_filter_changes_hash(self):
        h_no_filter = QueryCache._hash_query('q', tenant_id='s')
        h_with_filter = QueryCache._hash_query(
            'q', tenant_id='s', filter_metadata={'role': 'user'}
        )
        assert h_no_filter != h_with_filter


class TestQueryCacheTenantIsolation:
    """Two sessions asking the same question must not share cached results."""

    def test_store_and_get_tenant_scoped(self):
        cache = QueryCache()
        cache.store('how to test', [{'id': 1}], tenant_id='session-a')
        results = cache.get('how to test', tenant_id='session-a')
        assert results == [{'id': 1}]
        # Same query from a different tenant must miss.
        other = cache.get('how to test', tenant_id='session-b')
        assert other is None

    def test_invalidate_by_metadata_only_drops_matching_tenant(self):
        cache = QueryCache()
        cache.store(
            'q',
            [{'step_id': '1', 'role': 'user'}],
            tenant_id='session-a',
        )
        cache.store(
            'q',
            [{'step_id': '2', 'role': 'user'}],
            tenant_id='session-b',
        )
        evicted = cache.invalidate_by_metadata({'role': 'user'})
        assert evicted == 2

    def test_clear(self):
        cache = QueryCache()
        cache.store('q', [{'id': 1}], tenant_id='a')
        cache.store('q', [{'id': 2}], tenant_id='b')
        cache.clear()
        assert cache.get('q', tenant_id='a') is None
        assert cache.get('q', tenant_id='b') is None

    def test_lru_eviction_does_not_thundering_herd(self):
        """Cache must evict one entry at a time, not wipe the whole map."""
        cache = QueryCache(max_size=3)
        cache.store('a', [{'v': 1}], tenant_id='t')
        cache.store('b', [{'v': 2}], tenant_id='t')
        cache.store('c', [{'v': 3}], tenant_id='t')
        # Adding a 4th entry should evict only "a" (LRU), not all.
        cache.store('d', [{'v': 4}], tenant_id='t')
        assert cache.get('a', tenant_id='t') is None
        assert cache.get('b', tenant_id='t') is not None
        assert cache.get('c', tenant_id='t') is not None
        assert cache.get('d', tenant_id='t') is not None


class TestDefaultCollectionNames:
    def test_chromadb_backend_default_collection_name(self):
        signature = inspect.signature(ChromaDBBackend)
        assert signature.parameters['collection_name'].default == 'APP_memory'

    def test_sqlite_bm25_backend_default_collection_name(self):
        signature = inspect.signature(SQLiteBM25Backend)
        assert signature.parameters['collection_name'].default == 'APP_memory'

    def test_enhanced_vector_store_default_collection_name(self):
        signature = inspect.signature(EnhancedVectorStore)
        assert signature.parameters['collection_name'].default == 'APP_memory'


class TestVectorStoreWarmup:
    def test_chromadb_stats_does_not_force_model_load(self):
        backend = object.__new__(ChromaDBBackend)
        backend.collection = MagicMock()
        backend.collection.count.return_value = 3
        backend._model_name = 'test-embeddings'
        backend._model = None

        with patch.object(
            ChromaDBBackend,
            'model',
            new_callable=PropertyMock,
            side_effect=AssertionError('stats() should not touch model'),
        ):
            stats = backend.stats()

        assert stats == {
            'backend': 'ChromaDB (Local)',
            'num_documents': 3,
            'embedding_model': 'test-embeddings',
            'model_loaded': False,
        }

    def test_enhanced_vector_store_init_does_not_call_backend_stats(self):
        fake_backend = MagicMock()
        fake_backend.backend_name = 'Fake backend'
        fake_backend.stats.side_effect = AssertionError(
            '__init__ should not call backend.stats()'
        )

        with (
            patch(
                'backend.context.vector_store._local_vector_store.ChromaDBBackend',
                return_value=fake_backend,
            ),
            patch(
                'backend.context.vector_store._vector_store.SQLiteBM25Backend',
                return_value=MagicMock(),
            ),
        ):
            store = EnhancedVectorStore(collection_name='demo')

        assert store.backend is fake_backend
        fake_backend.stats.assert_not_called()
