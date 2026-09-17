"""Edge-case tests for QueryCache and EnhancedVectorStore."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from backend.context.vector_store import (
    EnhancedVectorStore,
    QueryCache,
    SQLiteBM25Backend,
)
from backend.context.vector_store import _vector_store as vs

TENANT_METADATA_KEY = vs.TENANT_METADATA_KEY


def make_store() -> EnhancedVectorStore:
    store = object.__new__(EnhancedVectorStore)
    store.cache = None
    store.config = {'final_k': 5}
    store.backend = MagicMock()
    return store


class TestResolveCurrentTenant:
    def test_returns_session_id(self) -> None:
        with (
            patch(
                'backend.context.memory.session_context.bind_session_context',
                return_value=None,
            ),
            patch(
                'backend.engine.tools.working_memory.get_current_session_id',
                return_value='  sess-1  ',
            ),
        ):
            assert vs._resolve_current_tenant() == 'sess-1'

    def test_returns_none_when_not_string(self) -> None:
        with (
            patch(
                'backend.context.memory.session_context.bind_session_context',
                return_value=None,
            ),
            patch(
                'backend.engine.tools.working_memory.get_current_session_id',
                return_value=None,
            ),
        ):
            assert vs._resolve_current_tenant() is None

    def test_returns_none_on_error(self) -> None:
        with patch(
            'backend.context.memory.session_context.bind_session_context',
            side_effect=RuntimeError('boom'),
        ):
            assert vs._resolve_current_tenant() is None


class TestQueryCacheInvalidate:
    def test_invalidate_by_step_ids(self) -> None:
        cache = QueryCache()
        cache.store('q1', [{'step_id': 'a'}])
        cache.store('q2', [{'step_id': 'b'}])
        cache.store('q3', [{'step_id': 'c'}])
        assert cache.invalidate_by_step_ids({'a', 'c'}) == 2
        assert cache.get('q1') is None
        assert cache.get('q2') == [{'step_id': 'b'}]
        assert cache.get('q3') is None

    def test_invalidate_by_step_ids_no_match(self) -> None:
        cache = QueryCache()
        cache.store('q1', [{'step_id': 'a'}])
        assert cache.invalidate_by_step_ids({'zzz'}) == 0

    def test_hash_query_json_error_falls_back_to_repr(self) -> None:
        class BadStr:
            def __str__(self) -> str:
                raise ValueError('boom')

        key = QueryCache._hash_query('q', filter_metadata={'k': BadStr()})
        assert len(key) == 24


class TestQueryCacheExtra:
    def test_get_expired_entry(self) -> None:
        cache = QueryCache(ttl=0)
        cache.store('q', [{'step_id': 'a'}])
        assert cache.get('q') is None

    def test_store_evicts_lru(self) -> None:
        cache = QueryCache(max_size=1)
        cache.store('a', [{'step_id': 'a'}])
        cache.store('b', [{'step_id': 'b'}])
        assert cache.get('a') is None
        assert cache.get('b') == [{'step_id': 'b'}]

    def test_clear_drops_entries(self) -> None:
        cache = QueryCache()
        cache.store('a', [{'step_id': 'a'}])
        cache.store('b', [{'step_id': 'b'}])
        cache.clear()
        assert cache.stats()['size'] == 0
        assert cache.get('a') is None


class TestEnhancedInit:
    def test_defaults_to_sqlite_bm25_backend(self, tmp_path) -> None:
        with patch(
            'backend.context.vector_store._local_vector_store.get_active_local_data_root',
            return_value=str(tmp_path),
        ):
            store = EnhancedVectorStore(collection_name='demo')
        assert isinstance(store.backend, SQLiteBM25Backend)
        assert store.cache is not None

    def test_injected_backend_is_used(self) -> None:
        fake_backend = MagicMock()
        fake_backend.backend_name = 'Fake'
        store = EnhancedVectorStore(collection_name='demo', backend=fake_backend)
        assert store.backend is fake_backend

    def test_cache_can_be_disabled(self) -> None:
        store = EnhancedVectorStore(backend=MagicMock(), enable_cache=False)
        assert store.cache is None
        assert store.config['caching_enabled'] is False


class TestAttachTenant:
    def test_adds_tenant_when_missing(self) -> None:
        assert EnhancedVectorStore._attach_tenant_metadata({'role': 'user'}, 's1') == {
            'role': 'user',
            TENANT_METADATA_KEY: 's1',
        }

    def test_none_metadata_creates_dict(self) -> None:
        assert EnhancedVectorStore._attach_tenant_metadata(None, 's1') == {
            TENANT_METADATA_KEY: 's1'
        }

    def test_existing_tenant_not_overwritten(self) -> None:
        assert EnhancedVectorStore._attach_tenant_metadata(
            {TENANT_METADATA_KEY: 's2'}, 's1'
        ) == {TENANT_METADATA_KEY: 's2'}

    def test_no_tenant_returns_copy(self) -> None:
        merged = EnhancedVectorStore._attach_tenant_metadata({'role': 'user'}, None)
        assert merged == {'role': 'user'}


class TestEnhancedAdd:
    def test_add_stamps_tenant(self) -> None:
        store = make_store()
        store.add('s1', 'user', 'h', 'r', 'text', {'role': 'user'}, tenant_id='sess')
        store.backend.add.assert_called_once()
        call = store.backend.add.call_args
        assert call.args[0] == 's1'
        assert call.args[5][TENANT_METADATA_KEY] == 'sess'

    def test_add_batch_default_metadatas(self) -> None:
        store = make_store()
        store.add_batch(
            ['s1', 's2'],
            ['user', 'user'],
            [None, None],
            [None, None],
            ['a', 'b'],
            tenant_id='sess',
        )
        store.backend.add_batch.assert_called_once()
        call = store.backend.add_batch.call_args
        assert call.args[5][0][TENANT_METADATA_KEY] == 'sess'
        assert call.args[5][1][TENANT_METADATA_KEY] == 'sess'

    async def test_async_add(self) -> None:
        store = make_store()
        await store.async_add('s1', 'user', None, None, 'text', tenant_id='sess')
        store.backend.add.assert_called_once()

    async def test_async_add_batch(self) -> None:
        store = make_store()
        await store.async_add_batch(
            ['s1'], ['user'], [None], [None], ['text'], tenant_id='sess'
        )
        store.backend.add_batch.assert_called_once()


class TestTryCachedSearch:
    def test_no_cache(self) -> None:
        store = make_store()
        assert (
            store._try_cached_search('q', 5, None, time.time(), tenant_id='t') is None
        )

    def test_cache_miss(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        assert (
            store._try_cached_search('q', 5, None, time.time(), tenant_id='t') is None
        )

    def test_cache_hit(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.cache.store('q', [{'step_id': 'a', 'score': 1.0}], tenant_id='t')
        result = store._try_cached_search('q', 5, None, time.time(), tenant_id='t')
        assert result == [{'step_id': 'a', 'score': 1.0}]


class TestSearch:
    def test_passes_tenant_filter_to_backend(self) -> None:
        store = make_store()
        store.backend.search.return_value = []
        store.search('q', k=7, tenant_id='t')
        store.backend.search.assert_called_once_with(
            'q', k=7, filter_metadata={TENANT_METADATA_KEY: 't'}
        )

    def test_tenant_resolved_when_missing(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.backend.search.return_value = [{'step_id': 'a', TENANT_METADATA_KEY: 't'}]
        with patch.object(vs, '_resolve_current_tenant', return_value='t'):
            results = store.search('q', tenant_id=None)
        assert results == [{'step_id': 'a', TENANT_METADATA_KEY: 't'}]

    def test_cache_hit_short_circuits(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.cache.store(
            'q', [{'step_id': 'a', TENANT_METADATA_KEY: 't'}], tenant_id='t'
        )
        results = store.search('q', tenant_id='t')
        assert results == [{'step_id': 'a', TENANT_METADATA_KEY: 't'}]
        store.backend.search.assert_not_called()

    def test_full_flow_with_cache_store(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.backend.search.return_value = [
            {'step_id': 'a', TENANT_METADATA_KEY: 't', 'score': 0.9}
        ]
        results = store.search('q', tenant_id='t')
        assert results == [{'step_id': 'a', TENANT_METADATA_KEY: 't', 'score': 0.9}]
        assert store.cache.get('q', tenant_id='t') == results

    def test_tenant_filter_drops_foreign_docs(self) -> None:
        store = make_store()
        store.backend.search.return_value = [
            {'step_id': 'a', TENANT_METADATA_KEY: 't1'},
            {'step_id': 'b', TENANT_METADATA_KEY: 't2'},
            {'step_id': 'c'},
        ]
        results = store.search('q', tenant_id='t1')
        assert [r['step_id'] for r in results] == ['a', 'c']

    def test_results_truncated_to_k(self) -> None:
        store = make_store()
        store.backend.search.return_value = [{'step_id': str(i)} for i in range(5)]
        assert len(store.search('q', k=2, tenant_id='t')) == 2

    def test_no_candidates_returns_empty(self) -> None:
        store = make_store()
        store.backend.search.return_value = []
        assert store.search('q', tenant_id='t') == []

    def test_backend_failure_returns_empty(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.backend.search.side_effect = RuntimeError('boom')
        assert store.search('q', tenant_id='t') == []
        assert store.cache.get('q', tenant_id='t') is None

    def test_search_without_cache(self) -> None:
        store = make_store()
        store.backend.search.return_value = [{'step_id': 'a'}]
        assert store.search('q', tenant_id='t') == [{'step_id': 'a'}]

    async def test_async_search(self) -> None:
        store = make_store()
        store.backend.search.return_value = []
        assert await store.async_search('q', tenant_id='t') == []


class TestKeywordSearchEndToEnd:
    """Real SQLite FTS5 backend: what search_history actually runs on."""

    def _store(self, tmp_path) -> EnhancedVectorStore:
        backend = SQLiteBM25Backend(collection_name='e2e', persist_directory=tmp_path)
        return EnhancedVectorStore(collection_name='e2e', backend=backend)

    def test_finds_identifier_and_ranks_best_match_first(self, tmp_path) -> None:
        store = self._store(tmp_path)
        store.add('e1', 'tool', None, None, 'Ran pytest: 12 passed', tenant_id='s')
        store.add(
            'e2',
            'tool',
            None,
            None,
            'KeyError in parse_config while loading settings.py: parse_config failed',
            tenant_id='s',
        )
        store.add('e3', 'assistant', None, None, 'Edited parse_config', tenant_id='s')
        results = store.search('parse_config KeyError', k=5, tenant_id='s')
        assert [r['step_id'] for r in results][:1] == ['e2']
        assert {r['step_id'] for r in results} == {'e2', 'e3'}

    def test_matches_file_paths_and_punctuation(self, tmp_path) -> None:
        store = self._store(tmp_path)
        store.add(
            'e1',
            'tool',
            None,
            None,
            'error in backend/app/main.py line 40',
            tenant_id='s',
        )
        results = store.search('backend/app/main.py', tenant_id='s')
        assert [r['step_id'] for r in results] == ['e1']

    def test_sessions_do_not_leak(self, tmp_path) -> None:
        store = self._store(tmp_path)
        store.add('a1', 'tool', None, None, 'deploy script failed', tenant_id='s1')
        store.add('b1', 'tool', None, None, 'deploy script failed', tenant_id='s2')
        assert [r['step_id'] for r in store.search('deploy', tenant_id='s1')] == ['a1']
        assert [r['step_id'] for r in store.search('deploy', tenant_id='s2')] == ['b1']


class TestDelete:
    def test_delete_by_metadata(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.backend.delete_by_metadata.return_value = 3
        store.cache.store('q', [{'step_id': 'a', 'role': 'user'}])
        assert store.delete_by_metadata({'role': 'user'}) == 3
        store.backend.delete_by_metadata.assert_called_once_with({'role': 'user'})
        assert store.cache.get('q') is None

    def test_delete_by_ids(self) -> None:
        store = make_store()
        store.cache = QueryCache()
        store.backend.delete_by_ids.return_value = 2
        store.cache.store('q', [{'step_id': 'a'}])
        assert store.delete_by_ids(['a']) == 2
        store.backend.delete_by_ids.assert_called_once_with(['a'])
        assert store.cache.get('q') is None


class TestStats:
    def test_stats_with_cache(self) -> None:
        store = make_store()
        store.backend.stats.return_value = {'backend': 'x', 'num_documents': 5}
        store.cache = QueryCache()
        stats = store.stats()
        assert stats['backend'] == 'x'
        assert stats['cache']['size'] == 0

    def test_stats_without_cache(self) -> None:
        store = make_store()
        store.backend.stats.return_value = {'backend': 'x'}
        assert 'cache' not in store.stats()


class TestApplyFilters:
    def test_no_filter_returns_first_k(self) -> None:
        results = [{'step_id': '1'}, {'step_id': '2'}, {'step_id': '3'}]
        assert EnhancedVectorStore._apply_filters(results, 2, None) == results[:2]

    def test_filter_keeps_matching(self) -> None:
        results = [
            {'step_id': '1', 'role': 'user'},
            {'step_id': '2', 'role': 'assistant'},
        ]
        filtered = EnhancedVectorStore._apply_filters(results, 5, {'role': 'user'})
        assert [r['step_id'] for r in filtered] == ['1']

    def test_tenant_filter(self) -> None:
        results = [
            {'step_id': '1', TENANT_METADATA_KEY: 't1'},
            {'step_id': '2', TENANT_METADATA_KEY: 't2'},
            {'step_id': '3'},
        ]
        filtered = EnhancedVectorStore._apply_filters(results, 5, None, tenant_id='t1')
        assert [r['step_id'] for r in filtered] == ['1', '3']

    def test_empty_results(self) -> None:
        assert EnhancedVectorStore._apply_filters([], 5, None) == []
