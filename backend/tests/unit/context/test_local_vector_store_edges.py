"""Edge-case tests for the SQLite FTS5 history search backend."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock, patch

from backend.context.vector_store import SQLiteBM25Backend


def make_sqlite_backend(tmp_path) -> SQLiteBM25Backend:
    return SQLiteBM25Backend('test-collection', persist_directory=tmp_path)


class TestSQLiteBasics:
    def test_default_persist_directory(self, tmp_path) -> None:
        with patch(
            'backend.context.vector_store._local_vector_store.get_active_local_data_root',
            return_value=str(tmp_path),
        ):
            backend = SQLiteBM25Backend('my-coll')
        assert backend.db_path == tmp_path / 'memory' / 'sqlite' / 'my-coll_fts.db'
        backend._close_conn()

    def test_close_conn(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        conn = backend._get_conn()
        assert conn is backend._get_conn()
        backend._close_conn()
        assert getattr(backend._local, 'conn', None) is None

    def test_close_conn_ignores_close_error(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend._get_conn()

        class BadConn:
            def close(self) -> None:
                raise OSError('boom')

        backend._local.conn = BadConn()
        backend._close_conn()
        assert getattr(backend._local, 'conn', None) is None

    def test_meta_string(self) -> None:
        assert SQLiteBM25Backend._meta_string(None) is None
        assert SQLiteBM25Backend._meta_string('x') == 'x'
        assert SQLiteBM25Backend._meta_string(42) == '42'
        assert SQLiteBM25Backend._meta_string(4.2) == '4.2'
        assert SQLiteBM25Backend._meta_string(True) == 'True'
        assert SQLiteBM25Backend._meta_string('') is None
        assert SQLiteBM25Backend._meta_string(['a']) is None

    def test_prepare_text(self) -> None:
        assert SQLiteBM25Backend._prepare_text('r', 'c') == 'r\nc'
        assert SQLiteBM25Backend._prepare_text(None, 'c') == 'c'
        assert SQLiteBM25Backend._prepare_text('r', None) == 'r'
        assert SQLiteBM25Backend._prepare_text(None, None) == ''

    def test_load_row_metadata(self) -> None:
        assert SQLiteBM25Backend._load_row_metadata('{"a": 1}') == {'a': 1}
        assert SQLiteBM25Backend._load_row_metadata('[1, 2]') == {}
        assert SQLiteBM25Backend._load_row_metadata('not json') == {}

    def test_metadata_matches_filter(self) -> None:
        assert SQLiteBM25Backend._metadata_matches_filter({'a': 1}, {'a': 1}) is True
        assert SQLiteBM25Backend._metadata_matches_filter({'a': 1}, {'a': 2}) is False
        assert SQLiteBM25Backend._metadata_matches_filter({'a': 1}, {'b': 1}) is False

    def test_append_fts_row(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        results: list[dict] = []
        added = backend._append_fts_row(
            results,
            step_id='s1',
            content='text',
            meta_json=json.dumps({'role': 'user'}),
            score=-0.5,
            filter_metadata={'role': 'assistant'},
            k=5,
        )
        assert added is False
        assert results == []
        added = backend._append_fts_row(
            results,
            step_id='s1',
            content='text',
            meta_json=json.dumps({'role': 'user'}),
            score=-0.5,
            filter_metadata=None,
            k=1,
        )
        assert added is True
        assert results[0]['step_id'] == 's1'
        assert results[0]['score'] == 0.5

    def test_build_fts_match_query(self) -> None:
        assert (
            SQLiteBM25Backend._build_fts_match_query('hello world')
            == '"hello" OR "world"'
        )
        assert SQLiteBM25Backend._build_fts_match_query('a b') is None
        assert SQLiteBM25Backend._build_fts_match_query('   ') is None
        assert (
            SQLiteBM25Backend._build_fts_match_query('say "hi"') == '"say" OR """hi"""'
        )

    def test_indexed_filter_clause(self) -> None:
        assert SQLiteBM25Backend._indexed_filter_clause(None) == ('', [])
        assert SQLiteBM25Backend._indexed_filter_clause({'session_id': 's'}) == (
            ' AND meta.session_id = ?',
            ['s'],
        )
        clause, params = SQLiteBM25Backend._indexed_filter_clause(
            {'session_id': 's', 'artifact_hash': 'h', 'role': 'r'}
        )
        assert clause == (
            ' AND meta.session_id = ? AND meta.artifact_hash = ? AND meta.role = ?'
        )
        assert params == ['s', 'h', 'r']
        assert SQLiteBM25Backend._indexed_filter_clause({'kind': 'x'}) == ('', [])


class TestSQLiteAdd:
    def test_add_and_stats(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add(
            's1', 'user', 'hash1', 'rationale', 'apple banana', {'session_id': 'sess'}
        )
        assert backend.stats()['num_documents'] == 1
        assert backend.db_path.exists()

    def test_add_batch_empty(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add_batch([], [], [], [], [])
        assert backend.stats()['num_documents'] == 0

    def test_add_batch_with_metadatas(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add_batch(
            ['s1', 's2'],
            ['user', 'assistant'],
            [None, 'h2'],
            [None, None],
            ['apple pie', 'orange juice'],
            [{'session_id': 'a'}, None],
        )
        assert backend.stats()['num_documents'] == 2
        results = backend.search('apple')
        assert results[0]['step_id'] == 's1'

    def test_add_batch_default_metadatas(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add_batch(
            ['s1', 's2'],
            ['user', 'user'],
            [None, None],
            [None, None],
            ['apple', 'orange'],
        )
        assert backend.stats()['num_documents'] == 2


class TestSQLiteSearch:
    def test_search_basic(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add(
            's1', 'user', None, None, 'apple banana cherry', {'session_id': 'a'}
        )
        backend.add(
            's2', 'assistant', None, None, 'apple pie recipe', {'session_id': 'b'}
        )
        results = backend.search('apple', k=2)
        assert len(results) == 2

    def test_search_indexed_filter(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple banana', {'session_id': 'a'})
        backend.add('s2', 'user', None, None, 'apple pie', {'session_id': 'b'})
        results = backend.search('apple', k=5, filter_metadata={'session_id': 'a'})
        assert [r['step_id'] for r in results] == ['s1']

    def test_search_residual_filter(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple tart', {'kind': 'dessert'})
        backend.add('s2', 'user', None, None, 'apple crisp', {'kind': 'other'})
        results = backend.search('apple', k=5, filter_metadata={'kind': 'dessert'})
        assert [r['step_id'] for r in results] == ['s1']

    def test_search_no_match_query(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', None)
        assert backend.search('a') == []

    def test_search_operational_error(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend._get_conn = MagicMock(side_effect=sqlite3.OperationalError('boom'))
        assert backend.search('apple') == []


class TestSQLiteDelete:
    def test_delete_by_metadata_empty_filter(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', None)
        assert backend.delete_by_metadata({}) == 0

    def test_delete_by_metadata_pure_indexed(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', {'session_id': 'a'})
        backend.add('s2', 'user', None, None, 'orange', {'session_id': 'b'})
        assert backend.delete_by_metadata({'session_id': 'a'}) == 1
        assert backend.stats()['num_documents'] == 1
        assert backend.search('apple') == []

    def test_delete_by_metadata_mixed(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', {'session_id': 'a', 'kind': 'x'})
        backend.add(
            's2', 'user', None, None, 'orange', {'session_id': 'a', 'kind': 'y'}
        )
        assert backend.delete_by_metadata({'session_id': 'a', 'kind': 'x'}) == 1
        assert backend.stats()['num_documents'] == 1

    def test_delete_by_metadata_python_scan(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', {'kind': 'x'})
        backend.add('s2', 'user', None, None, 'orange', {'kind': 'y'})
        assert backend.delete_by_metadata({'kind': 'x'}) == 1
        assert backend.stats()['num_documents'] == 1

    def test_delete_by_metadata_no_match(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', {'kind': 'x'})
        assert backend.delete_by_metadata({'kind': 'zzz'}) == 0

    def test_delete_by_ids(self, tmp_path) -> None:
        backend = make_sqlite_backend(tmp_path)
        backend.add('s1', 'user', None, None, 'apple', None)
        backend.add('s2', 'user', None, None, 'orange', None)
        assert backend.delete_by_ids([]) == 0
        assert backend.delete_by_ids(['s1']) == 1
        assert backend.stats()['num_documents'] == 1
        assert backend.delete_by_ids(['nope']) == 0
