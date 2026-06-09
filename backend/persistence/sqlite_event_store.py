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

import contextlib
import copy
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from backend.core import json_compat as json
from backend.ledger.integrity import (
    embed_checksum,
    repair_payload_checksum,
    verify_event_integrity,
)

_SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAYLOAD_BYTES = 25 * 1024 * 1024

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


class SQLiteAppendOnlyViolation(RuntimeError):
    """Raised when a write would violate append-only ledger semantics."""


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
        self._closed = False
        # Dedicated thread-local for read connections - WAL mode allows concurrent readers
        self._local = threading.local()
        self._read_conns: set[sqlite3.Connection] = set()
        self._read_conns_lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _max_payload_bytes() -> int:
        raw = str(os.getenv('GRINTA_SQLITE_EVENT_MAX_PAYLOAD_BYTES', '')).strip()
        if raw:
            try:
                v = int(raw)
                if v > 0:
                    return v
            except Exception:
                pass
        return DEFAULT_MAX_PAYLOAD_BYTES

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError('SQLiteEventStore is closed')

    def _get_conn(self) -> sqlite3.Connection:
        self._ensure_open()
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.execute('PRAGMA journal_mode=WAL')
            # WAL + synchronous=NORMAL provides equivalent crash safety to
            # FULL with significantly better write throughput. The WAL file
            # is fsync'd before the database, so power-loss safety is
            # maintained. See SQLite docs: "When synchronous is NORMAL
            # (Normal), the SQLite database engine will still sync at the
            # most critical moments, but less often than in FULL mode."
            self._conn.execute('PRAGMA synchronous=FULL')
            self._conn.execute('PRAGMA busy_timeout=5000')
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _get_read_conn(self) -> sqlite3.Connection:
        """Return a thread-local read-only connection for concurrent queries."""
        self._ensure_open()
        conn = getattr(self._local, 'read_conn', None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA query_only=ON')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.row_factory = sqlite3.Row
            self._local.read_conn = conn
            with self._read_conns_lock:
                self._read_conns.add(conn)
        return conn

    def _ensure_schema(self) -> None:
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.executescript(_CREATE_SQL)
                # Record schema version
                conn.execute(
                    'INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)',
                    ('schema_version', str(_SCHEMA_VERSION)),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def __del__(self) -> None:
        """Ensure connection closure during garbage collection."""
        try:
            self.close()
        except Exception:
            pass

    def check_integrity(self, *, verify_checksums: bool = True) -> bool:
        """Run SQLite and application-level integrity checks.

        SQLite's ``integrity_check`` validates database pages and indexes. It
        does not know whether event payloads match their row IDs or embedded
        Grinta checksums, so this method validates both layers.
        """
        try:
            conn = self._get_read_conn()
            rows = conn.execute('PRAGMA integrity_check').fetchall()
            results = [r[0] for r in rows]
            if results != ['ok']:
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
        return self.check_application_integrity(verify_checksums=verify_checksums)

    def check_application_integrity(self, *, verify_checksums: bool = True) -> bool:
        """Validate persisted event payload IDs and checksums."""
        try:
            conn = self._get_read_conn()
            rows = conn.execute('SELECT id, payload FROM events ORDER BY id').fetchall()
            previous_id = -1
            for row in rows:
                event_id = int(row['id'])
                if event_id <= previous_id:
                    logger.error(
                        'SQLite event order violation for %s: id=%s after id=%s',
                        self._db_path,
                        event_id,
                        previous_id,
                    )
                    return False
                previous_id = event_id
                data = json.loads(row['payload'])
                payload_id = data.get('id')
                if payload_id is not None and payload_id != event_id:
                    logger.error(
                        'SQLite event id mismatch for %s: row id=%s payload id=%r',
                        self._db_path,
                        event_id,
                        payload_id,
                    )
                    return False
                if verify_checksums and not verify_event_integrity(data, event_id):
                    logger.error(
                        'SQLite event checksum mismatch for %s event id=%s',
                        self._db_path,
                        event_id,
                    )
                    return False
            return True
        except Exception as exc:
            logger.error(
                'SQLite application integrity check failed for %s: %s',
                self._db_path,
                exc,
            )
            return False

    def close(self) -> None:
        """Close the database connections."""
        with self._write_lock:
            if self._closed:
                return
            self._closed = True
            read_conn = getattr(self._local, 'read_conn', None)
            if read_conn is not None:
                with contextlib.suppress(Exception):
                    read_conn.close()
                self._local.read_conn = None
            with self._read_conns_lock:
                to_close = list(self._read_conns)
                self._read_conns.clear()
            for conn in to_close:
                with contextlib.suppress(Exception):
                    conn.close()
            if self._conn is not None:
                with contextlib.suppress(Exception):
                    self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _prepare_payload(self, event_id: int, event_dict: dict[str, Any]) -> str:
        """Return canonical JSON payload with event ID and checksum embedded."""
        payload_dict = copy.deepcopy(event_dict)
        payload_id = payload_dict.get('id')
        if payload_id is not None and payload_id != event_id:
            raise ValueError(
                f'Event payload id mismatch: row id={event_id}, payload id={payload_id!r}'
            )
        payload_dict['id'] = event_id
        return json.dumps(embed_checksum(payload_dict), ensure_ascii=False, default=str)

    def repair_event_checksums(self) -> int:
        """Re-embed checksums for rows whose stored digest no longer matches."""
        fixed = 0
        with self._write_lock:
            conn = self._get_conn()
            rows = conn.execute('SELECT id, payload FROM events ORDER BY id').fetchall()
            updates: list[tuple[str, int]] = []
            for row in rows:
                event_id = int(row['id'])
                data = json.loads(row['payload'])
                if verify_event_integrity(data, event_id):
                    continue
                repaired = repair_payload_checksum(data, event_id=event_id)
                updates.append(
                    (
                        json.dumps(repaired, ensure_ascii=False, default=str),
                        event_id,
                    )
                )
            if not updates:
                return 0
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.executemany(
                    'UPDATE events SET payload = ? WHERE id = ?',
                    updates,
                )
                conn.commit()
                fixed = len(updates)
            except Exception:
                conn.rollback()
                raise
        if fixed:
            logger.info(
                'Repaired %d SQLite event checksum(s) in %s',
                fixed,
                self._db_path,
            )
        return fixed

    def write_event(self, event_id: int, event_dict: dict[str, Any]) -> None:
        """Persist a single event.

        Args:
            event_id: Unique, monotonically increasing event ID.
            event_dict: Serialised event dictionary (must be JSON-safe).
        """
        import time as _time

        payload = self._prepare_payload(event_id, event_dict)
        timestamp = event_dict.get('timestamp', _time.time())
        if not isinstance(timestamp, (int, float)):
            timestamp_attr = getattr(timestamp, 'timestamp', None)
            timestamp = (
                float(timestamp_attr()) if callable(timestamp_attr) else _time.time()
            )
        event_type = event_dict.get('action', event_dict.get('observation', 'unknown'))
        source = event_dict.get('source')

        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute(
                    'INSERT INTO events (id, timestamp, event_type, source, payload) VALUES (?, ?, ?, ?, ?)',
                    (event_id, timestamp, event_type, source, payload),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise SQLiteAppendOnlyViolation(
                    f'Event id {event_id} already exists in append-only ledger {self._db_path}'
                ) from exc
            except Exception:
                conn.rollback()
                raise

    def write_events_batch(self, events: list[tuple[int, dict[str, Any]]]) -> None:
        """Persist multiple events in a single transaction.

        Uses executemany for efficient bulk insertion.

        Args:
            events: List of ``(event_id, event_dict)`` pairs.
        """
        import time as _time

        if not events:
            return
        ids = [event_id for event_id, _ in events]
        if len(ids) != len(set(ids)):
            raise SQLiteAppendOnlyViolation('Batch contains duplicate event IDs')

        rows: list[tuple[int, float, str, str | None, str]] = []
        for event_id, event_dict in events:
            payload = self._prepare_payload(event_id, event_dict)
            timestamp = event_dict.get('timestamp', _time.time())
            if not isinstance(timestamp, (int, float)):
                timestamp_attr = getattr(timestamp, 'timestamp', None)
                timestamp = (
                    float(timestamp_attr())
                    if callable(timestamp_attr)
                    else _time.time()
                )
            event_type = event_dict.get(
                'action', event_dict.get('observation', 'unknown')
            )
            source = event_dict.get('source', None)
            rows.append((event_id, timestamp, event_type, source, payload))

        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.executemany(
                    'INSERT INTO events (id, timestamp, event_type, source, payload) VALUES (?, ?, ?, ?, ?)',
                    rows,
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise SQLiteAppendOnlyViolation(
                    f'Batch would overwrite existing event(s) in append-only ledger {self._db_path}'
                ) from exc
            except Exception:
                conn.rollback()
                raise

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
        limit = self._max_payload_bytes()
        # Single query to avoid TOCTOU race between size check and payload fetch.
        row = conn.execute(
            'SELECT length(payload) AS sz, payload FROM events WHERE id = ?',
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        size = int(row['sz'] or 0)
        if size > limit:
            raise ValueError(
                f'Event payload too large ({size} bytes) for id={event_id}'
            )
        data = json.loads(row['payload'])
        payload_id = data.get('id')
        if payload_id is not None and payload_id != event_id:
            raise ValueError(f'Event {event_id}: payload id mismatch ({payload_id!r})')
        if not verify_event_integrity(data, event_id):
            raise ValueError(
                f'Event {event_id}: integrity checksum mismatch in SQLite ledger'
            )
        return data

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

        sql = f'SELECT id, length(payload) AS sz, payload FROM events WHERE {" AND ".join(clauses)} ORDER BY id'  # nosec B608
        if limit is not None:
            sql += ' LIMIT ?'
            params.append(limit)

        conn = self._get_read_conn()
        rows = conn.execute(sql, params).fetchall()

        results: list[dict[str, Any]] = []
        max_payload_bytes = self._max_payload_bytes()
        for r in rows:
            row_id = int(r['id'])
            size = int(r['sz'] or 0)
            if size > max_payload_bytes:
                raise ValueError(
                    f'Event payload too large ({size} bytes) for id={row_id}'
                )
            data = json.loads(r['payload'])
            event_id = data.get('id')
            if event_id is not None and event_id != row_id:
                raise ValueError(f'Event {row_id}: payload id mismatch ({event_id!r})')
            if not verify_event_integrity(data, row_id):
                logger.warning(
                    'Skipping SQLite event id=%s with checksum mismatch in %s',
                    row_id,
                    self._db_path,
                )
                continue
            results.append(data)
        return results

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

    @staticmethod
    def _destructive_delete_enabled() -> bool:
        return str(
            os.getenv('GRINTA_SQLITE_LEDGER_ALLOW_DESTRUCTIVE_DELETE', '')
        ).lower() in ('1', 'true', 'yes')

    def delete_event(self, event_id: int) -> None:
        """Delete a single event."""
        if not self._destructive_delete_enabled():
            raise SQLiteAppendOnlyViolation(
                'delete_event is disabled for the append-only SQLite ledger'
            )
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute('DELETE FROM events WHERE id = ?', (event_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def delete_from(self, start_id: int) -> int:
        """Delete all events with ID >= *start_id*.

        Returns:
            Number of deleted rows.
        """
        if not self._destructive_delete_enabled():
            raise SQLiteAppendOnlyViolation(
                'delete_from is disabled for the append-only SQLite ledger'
            )
        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute('DELETE FROM events WHERE id >= ?', (start_id,))
                conn.commit()
                return cursor.rowcount
            except Exception:
                conn.rollback()
                raise

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f'SQLiteEventStore(db_path={self._db_path!r})'


__all__ = ['SQLiteAppendOnlyViolation', 'SQLiteEventStore']
