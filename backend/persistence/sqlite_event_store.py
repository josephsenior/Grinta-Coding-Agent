"""SQLite-backed event persistence for high-throughput conversations.

Replaces per-file JSON event storage with a single SQLite database per
conversation, dramatically reducing filesystem overhead for long sessions.

Usage:
    store = SQLiteEventStore(db_path="/data/sessions/abc123/events.db")
    store.write_event(0, {"id": 0, "action": "message", ...})
    event = store.read_event(0)
    all_events = store.list_events()
    store.close()

The module is designed as a **drop-in accelerator** — the existing
``FileStore``-based ``EventStore`` continues to work, and this class
can be used alongside or as a replacement for the file-based path
in ``EventStream._persist_event()``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from backend.core import json_compat as json

_SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    timestamp   REAL    NOT NULL,
    event_type  TEXT    NOT NULL,
    source      TEXT,
    payload     TEXT    NOT NULL          -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_events_type   ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SQLiteEventStore:
    """Thread-safe SQLite store for conversation events.

    Each instance manages a single database file. WAL mode enables concurrent
    readers alongside a single writer.  Writes are serialised via ``_write_lock``
    while reads use a separate ``_read_conn`` without holding any Python-level
    lock, allowing concurrent read operations.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        # Dedicated read connection — WAL mode allows concurrent readers
        self._read_conn: sqlite3.Connection | None = None
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.execute('PRAGMA journal_mode=WAL')
            self._conn.execute('PRAGMA synchronous=NORMAL')
            self._conn.execute('PRAGMA busy_timeout=5000')
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _get_read_conn(self) -> sqlite3.Connection:
        """Return a read-only connection for concurrent queries."""
        if self._read_conn is None:
            self._read_conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._read_conn.execute('PRAGMA journal_mode=WAL')
            self._read_conn.execute('PRAGMA query_only=ON')
            self._read_conn.execute('PRAGMA busy_timeout=5000')
            self._read_conn.row_factory = sqlite3.Row
        return self._read_conn

    def _ensure_schema(self) -> None:
        with self._write_lock:
            conn = self._get_conn()
            conn.executescript(_CREATE_SQL)
            # Record schema version
            conn.execute(
                'INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)',
                ('schema_version', str(_SCHEMA_VERSION)),
            )
            conn.commit()

    def check_integrity(self) -> bool:
        """Run PRAGMA integrity_check and return True if the database is healthy.

        Called once on startup.  A corrupted database returns a list of error
        strings from SQLite; an empty DB or a healthy one returns ``['ok']``.
        """
        try:
            conn = self._get_read_conn()
            rows = conn.execute('PRAGMA integrity_check').fetchall()
            results = [r[0] for r in rows]
            if results == ['ok']:
                return True
            logger.error(
                'SQLite integrity check FAILED for %s: %s',
                self._db_path,
                '; '.join(results[:5]),  # cap output length
            )
            return False
        except Exception as exc:
            logger.error(
                'SQLite integrity check raised an exception for %s: %s',
                self._db_path,
                exc,
            )
            return False

    def close(self) -> None:
        """Close the database connections."""
        with self._write_lock:
            if self._read_conn is not None:
                self._read_conn.close()
                self._read_conn = None
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_event(self, event_id: int, event_dict: dict[str, Any]) -> None:
        """Persist a single event.

        Args:
            event_id: Unique, monotonically increasing event ID.
            event_dict: Serialised event dictionary (must be JSON-safe).
        """
        import time as _time

        payload = json.dumps(event_dict, ensure_ascii=False)
        timestamp = event_dict.get('timestamp', _time.time())
        event_type = event_dict.get('action', event_dict.get('observation', 'unknown'))
        source = event_dict.get('source')

        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                'INSERT OR REPLACE INTO events (id, timestamp, event_type, source, payload) VALUES (?, ?, ?, ?, ?)',
                (event_id, timestamp, event_type, source, payload),
            )
            conn.commit()

    def write_events_batch(self, events: list[tuple[int, dict[str, Any]]]) -> None:
        """Persist multiple events in a single transaction.

        Uses executemany for efficient bulk insertion.

        Args:
            events: List of ``(event_id, event_dict)`` pairs.
        """
        import time as _time

        rows: list[tuple[int, float, str, str | None, str]] = []
        for event_id, event_dict in events:
            payload = json.dumps(event_dict, ensure_ascii=False)
            timestamp = event_dict.get('timestamp', _time.time())
            event_type = event_dict.get(
                'action', event_dict.get('observation', 'unknown')
            )
            source = event_dict.get('source', None)
            rows.append((event_id, timestamp, event_type, source, payload))

        with self._write_lock:
            conn = self._get_conn()
            conn.executemany(
                'INSERT OR REPLACE INTO events (id, timestamp, event_type, source, payload) VALUES (?, ?, ?, ?, ?)',
                rows,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_event(self, event_id: int) -> dict[str, Any] | None:
        """Read a single event by ID.

        Uses the dedicated read connection — no write lock contention.

        Returns:
            Parsed event dict, or ``None`` if not found.
        """
        conn = self._get_read_conn()
        row = conn.execute(
            'SELECT payload FROM events WHERE id = ?', (event_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row['payload'])

    def list_events(
        self,
        start_id: int = 0,
        end_id: int | None = None,
        event_type: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List events with optional filtering.

        Args:
            start_id: Minimum event ID (inclusive).
            end_id: Maximum event ID (exclusive). ``None`` means no upper bound.
            event_type: Filter by event type (action name).
            source: Filter by source.
            limit: Maximum number of events to return.

        Returns:
            List of parsed event dicts ordered by ID.
        """
        clauses: list[str] = ['id >= ?']
        params: list[Any] = [start_id]

        if end_id is not None:
            clauses.append('id < ?')
            params.append(end_id)
        if event_type is not None:
            clauses.append('event_type = ?')
            params.append(event_type)
        if source is not None:
            clauses.append('source = ?')
            params.append(source)

        sql = f'SELECT payload FROM events WHERE {" AND ".join(clauses)} ORDER BY id'
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(limit)

        conn = self._get_read_conn()
        rows = conn.execute(sql, params).fetchall()

        return [json.loads(r['payload']) for r in rows]

    def count(self) -> int:
        """Return the total number of persisted events."""
        conn = self._get_read_conn()
        row = conn.execute('SELECT COUNT(*) AS cnt FROM events').fetchone()
        return row['cnt'] if row else 0

    def max_id(self) -> int:
        """Return the highest event ID, or -1 if empty."""
        conn = self._get_read_conn()
        row = conn.execute('SELECT MAX(id) AS m FROM events').fetchone()
        val = row['m'] if row else None
        return val if val is not None else -1

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_event(self, event_id: int) -> None:
        """Delete a single event."""
        with self._write_lock:
            conn = self._get_conn()
            conn.execute('DELETE FROM events WHERE id = ?', (event_id,))
            conn.commit()

    def delete_from(self, start_id: int) -> int:
        """Delete all events with ID >= *start_id*.

        Returns:
            Number of deleted rows.
        """
        with self._write_lock:
            conn = self._get_conn()
            cursor = conn.execute('DELETE FROM events WHERE id >= ?', (start_id,))
            conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f'SQLiteEventStore(db_path={self._db_path!r})'


__all__ = ['SQLiteEventStore']
