"""Storage backends for history search.

``VectorBackend`` is the pluggable interface; ``SQLiteBM25Backend`` (SQLite
FTS5 keyword search, standard library only) is the default and only shipped
implementation.
"""

from __future__ import annotations

import json
import logging
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


class SQLiteBM25Backend(VectorBackend):
    """Local SQLite FTS5 backend for BM25 lexical search."""

    backend_name = 'SQLite FTS5 (BM25)'

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
        # Sidecar table with indexed columns so metadata filters and
        # tenant (session) scoping are O(log n) lookups instead of full
        # table scans. Joins back to ``docs.rowid``.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS docs_meta (
                rowid INTEGER PRIMARY KEY,
                step_id TEXT NOT NULL,
                role TEXT,
                session_id TEXT,
                artifact_hash TEXT,
                timestamp REAL
            )
        """)
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_docs_meta_session_id '
            'ON docs_meta(session_id)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_docs_meta_step_id ON docs_meta(step_id)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_docs_meta_artifact_hash '
            'ON docs_meta(artifact_hash)'
        )
        conn.commit()

    @staticmethod
    def _meta_string(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            text = str(value)
            return text if text else None
        return None

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
        cursor = conn.execute(
            'INSERT OR REPLACE INTO docs (step_id, role, content, metadata) '
            'VALUES (?, ?, ?, ?)',
            (step_id, role, text[:2000], json.dumps(doc_metadata)),
        )
        rowid = cursor.lastrowid
        conn.execute(
            'INSERT OR REPLACE INTO docs_meta '
            '(rowid, step_id, role, session_id, artifact_hash, timestamp) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (
                rowid,
                step_id,
                self._meta_string(role),
                self._meta_string(doc_metadata.get('session_id')),
                self._meta_string(artifact_hash),
                float(doc_metadata.get('timestamp') or time.time()),
            ),
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
        now = time.time()
        rows = []
        meta_rows = []
        for idx, step_id in enumerate(step_ids):
            text = self._prepare_text(rationales[idx], content_texts[idx])
            doc_metadata = {
                'step_id': step_id,
                'role': roles[idx],
                'timestamp': now,
                **(metadatas[idx] or {}),
            }
            if artifact_hashes[idx]:
                doc_metadata['artifact_hash'] = artifact_hashes[idx]
            rows.append((step_id, roles[idx], text[:2000], json.dumps(doc_metadata)))
            meta_rows.append(
                (
                    step_id,
                    self._meta_string(roles[idx]),
                    self._meta_string(doc_metadata.get('session_id')),
                    self._meta_string(artifact_hashes[idx]),
                    float(doc_metadata.get('timestamp') or now),
                )
            )

        # INSERT OR REPLACE into the FTS table returns the rowid of the
        # inserted/replaced row, but only if we issue one statement at a
        # time (sqlite3's lastrowid is undefined for executemany). We
        # therefore use a single transaction and re-select the rowid via
        # step_id.
        with conn:
            conn.executemany(
                'INSERT OR REPLACE INTO docs (step_id, role, content, metadata) '
                'VALUES (?, ?, ?, ?)',
                rows,
            )
            conn.executemany(
                'INSERT OR REPLACE INTO docs_meta '
                '(rowid, step_id, role, session_id, artifact_hash, timestamp) '
                'SELECT rowid, ?, ?, ?, ?, ? FROM docs WHERE step_id = ?',
                [
                    (
                        step_id,
                        role,
                        session_id,
                        artifact_hash,
                        timestamp,
                        step_id,
                    )
                    for (
                        step_id,
                        role,
                        session_id,
                        artifact_hash,
                        timestamp,
                    ) in meta_rows
                ],
            )

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

    @staticmethod
    def _build_fts_match_query(query: str) -> str | None:
        """Build a parameterized FTS5 MATCH expression from user input.

        Splits on whitespace, drops empty/short tokens, and quotes each
        remaining token so user-supplied punctuation and FTS5 operators
        cannot break the query. The OR join preserves recall for the
        typical keyword search pattern.
        """
        tokens = [tok for tok in query.split() if tok and len(tok) > 1]
        if not tokens:
            return None
        # Quote each token to neutralise any FTS5 special characters and
        # allow non-alphanumeric content (paths, identifiers, code).
        quoted = ['"' + tok.replace('"', '""') + '"' for tok in tokens]
        return ' OR '.join(quoted)

    @staticmethod
    def _indexed_filter_clause(
        filter_metadata: dict[str, Any] | None,
    ) -> tuple[str, list[Any]]:
        """Return an SQL fragment + bound params using indexed meta columns.

        Only the columns with dedicated indexes (``session_id``,
        ``artifact_hash``, ``role``) can be pushed into SQL. Anything else
        has to fall back to the JSON metadata filter applied in Python.
        """
        if not filter_metadata:
            return '', []
        clauses: list[str] = []
        params: list[Any] = []
        for key in ('session_id', 'artifact_hash', 'role'):
            if key in filter_metadata:
                clauses.append(f'meta.{key} = ?')
                params.append(filter_metadata[key])
        if not clauses:
            return '', []
        return ' AND ' + ' AND '.join(clauses), params

    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        match_query = self._build_fts_match_query(query)
        if not match_query:
            return []

        # We over-fetch a bit because some rows may be filtered out by
        # the Python-side metadata check below.
        fetch_k = max(k * 3, k + 10)

        indexed_sql, indexed_params = self._indexed_filter_clause(filter_metadata)
        # Determine the residual filter (anything that didn't map to a
        # column) so the Python loop still enforces the rest.
        residual = {
            key: value
            for key, value in (filter_metadata or {}).items()
            if key not in {'session_id', 'artifact_hash', 'role'}
        }

        try:
            conn = self._get_conn()
            cursor = conn.execute(
                f"""
                SELECT docs.step_id, docs.content, docs.metadata,
                       bm25(docs) as score
                FROM docs
                JOIN docs_meta AS meta ON meta.rowid = docs.rowid
                WHERE docs MATCH ?
                  {indexed_sql}
                ORDER BY score ASC
                LIMIT ?
                """,
                (match_query, *indexed_params, fetch_k),
            )

            results: list[dict[str, Any]] = []
            for step_id, content, meta_json, score in cursor:
                if residual and not self._metadata_matches_filter(
                    self._load_row_metadata(meta_json), residual
                ):
                    continue
                if self._append_fts_row(
                    results,
                    step_id=step_id,
                    content=content,
                    meta_json=meta_json,
                    score=score,
                    filter_metadata=None,  # already enforced above
                    k=k,
                ):
                    break

            return results
        except sqlite3.OperationalError as e:
            logger.warning("SQLite FTS search failed for query '%s': %s", query, e)
            return []

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents whose stored metadata matches all filter criteria.

        Uses the ``docs_meta`` sidecar to push ``session_id``,
        ``artifact_hash`` and ``role`` into indexed ``WHERE`` clauses so
        large collections are not scanned in Python.
        """
        if not filter_metadata:
            return 0

        conn = self._get_conn()
        indexed_sql, indexed_params = self._indexed_filter_clause(filter_metadata)
        residual = {
            key: value
            for key, value in filter_metadata.items()
            if key not in {'session_id', 'artifact_hash', 'role'}
        }

        if indexed_sql and not residual:
            # Pure indexed path: single DELETE statement, no Python scan.
            cursor = conn.execute(
                f'DELETE FROM docs WHERE rowid IN '
                f'(SELECT rowid FROM docs_meta AS meta WHERE 1=1 {indexed_sql})',
                indexed_params,
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

        # Mixed path: indexed pre-filter to bound the Python scan.
        if indexed_sql:
            cursor = conn.execute(
                f'SELECT docs.rowid, docs.metadata FROM docs '
                f'JOIN docs_meta AS meta ON meta.rowid = docs.rowid '
                f'WHERE 1=1 {indexed_sql}',
                indexed_params,
            )
        else:
            cursor = conn.execute('SELECT rowid, metadata FROM docs')

        ids_to_delete: list[int] = []
        for rowid, meta_json in cursor:
            meta = self._load_row_metadata(meta_json)
            if self._metadata_matches_filter(meta, filter_metadata):
                ids_to_delete.append(rowid)

        if not ids_to_delete:
            return 0

        with conn:
            conn.executemany(
                'DELETE FROM docs WHERE rowid = ?',
                [(rid,) for rid in ids_to_delete],
            )
            conn.executemany(
                'DELETE FROM docs_meta WHERE rowid = ?',
                [(rid,) for rid in ids_to_delete],
            )
        return len(ids_to_delete)

    def delete_by_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        conn = self._get_conn()
        with conn:
            cursor = conn.cursor()
            cursor.executemany(
                'DELETE FROM docs WHERE step_id = ?', [(i,) for i in ids]
            )
            fts_deleted = cursor.rowcount
            cursor.executemany(
                'DELETE FROM docs_meta WHERE step_id = ?', [(i,) for i in ids]
            )
        return fts_deleted

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


__all__ = ['SQLiteBM25Backend', 'VectorBackend']
