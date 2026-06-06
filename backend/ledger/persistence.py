"""Event persistence with WAL crash-recovery and optional SQLite accelerator.

Encapsulates file-based event writing, write-ahead log markers, cache page
management, and the optional durable async writer.  Used as a composition
helper by :class:`~backend.ledger.stream.EventStream`.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar

from backend.core.io_adapters import json
from backend.core.logger import app_logger as logger
from backend.ledger.durable_writer import DurableEventWriter, PersistedEvent
from backend.ledger.integrity import embed_checksum
from backend.persistence.locations import get_conversation_events_dir

if TYPE_CHECKING:
    from backend.persistence import FileStore


def _file_store_fs_root(file_store: FileStore) -> str | None:
    """Directory for session-relative SQLite paths; ``None`` if store is not disk-backed."""
    root = getattr(file_store, 'root', '') or ''
    if isinstance(root, str) and root.strip():
        return root
    if hasattr(file_store, 'get_base_path'):
        try:
            p = file_store.get_base_path()
            if isinstance(p, str) and p.strip():
                return p
        except Exception:
            pass
    return None


class EventPersistence:
    """Handles durable event persistence with WAL crash recovery.

    Parameters
    ----------
    sid:
        Session identifier.
    file_store:
        Backend file storage implementation.
    user_id:
        Optional user scoping ID.
    async_write:
        Whether to enable the ``DurableEventWriter`` for async persistence.
    get_filename_for_id:
        Callable ``(event_id, user_id) -> str`` for canonical file paths.
    get_filename_for_cache:
        Callable ``(start, end) -> str`` for cache page paths.
    cache_size:
        Number of events per cache page.
    recent_persist_failures:
        Shared deque for recording failure timestamps (rate window).
    """

    _CRITICAL_ACTIONS: ClassVar[set[str]] = {
        'change_agent_state',
        'reject',
    }
    _CRITICAL_OBSERVATIONS: ClassVar[set[str]] = {
        'error',
        'agent_state_changed',
        'user_rejected',
    }

    @classmethod
    def is_critical_event(cls, event: Any) -> bool:
        """Check whether an Event instance represents a critical control/error event."""
        action_name = getattr(event, 'action', None)
        if isinstance(action_name, str):
            return action_name in cls._CRITICAL_ACTIONS
        observation_name = getattr(event, 'observation', None)
        if isinstance(observation_name, str):
            return observation_name in cls._CRITICAL_OBSERVATIONS
        return False

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        user_id: str | None,
        *,
        async_write: bool = False,
        get_filename_for_id: Any = None,
        get_filename_for_cache: Any = None,
        cache_size: int = 50,
        recent_persist_failures: deque[float] | None = None,
        existing_sqlite_store: Any = None,
    ) -> None:
        self.sid = sid
        self.file_store = file_store
        self.user_id = user_id
        self._get_filename_for_id = get_filename_for_id
        self._get_filename_for_cache = get_filename_for_cache
        self._cache_size = cache_size
        self._recent_persist_failures = (
            recent_persist_failures
            if recent_persist_failures is not None
            else deque(maxlen=500)
        )
        self._persist_failure_window_seconds: int = 600
        self.stats: dict[str, int] = {
            'persist_failures': 0,
            'cache_write_failures': 0,
            'critical_sync_persistence': 0,
            'durable_enqueue_failures': 0,
        }
        self._last_confirmed_event_id: int | None = None
        self._last_confirmed_critical_event_id: int | None = None
        self._last_persisted_at_monotonic: float | None = None
        self._last_enqueued_event_id: int | None = None
        self._last_persist_failure_at_monotonic: float | None = None
        self._last_persistence_mode: str | None = None

        # Optional SQLite accelerator — reuse an existing store from the parent
        # EventStream to avoid dual SQLite connections to the same events.db.
        self._sqlite_store: Any = existing_sqlite_store
        if self._sqlite_store is None and str(
            os.getenv('APP_SQLITE_EVENTS', 'true')
        ).lower() in (
            '1',
            'true',
            'yes',
        ):
            try:
                from backend.persistence.sqlite_event_store import SQLiteEventStore

                fs_root = _file_store_fs_root(file_store)
                if fs_root:
                    events_dir = get_conversation_events_dir(sid, user_id)
                    db_path = os.path.join(
                        fs_root,
                        events_dir,
                        'events.db',
                    )
                    self._sqlite_store = SQLiteEventStore(db_path=db_path)
                    logger.info(
                        'SQLite event accelerator enabled for session %s',
                        sid,
                    )
            except Exception as exc:
                raise RuntimeError(
                    f'Failed to initialise authoritative SQLite event store for session {sid}'
                ) from exc

        if self._sqlite_store is not None:
            self._migrate_legacy_event_files_to_sqlite()

        # Async durable writer
        self._durable_writer: DurableEventWriter | None = None
        if async_write:
            try:
                self._durable_writer = DurableEventWriter(file_store)
                self._durable_writer.start()
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    'Failed to start DurableEventWriter, falling back to sync persistence: %s',
                    exc,
                )
                self._durable_writer = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def persist_event(
        self,
        payload: dict[str, Any],
        event_id: int,
        cache_payload: tuple[str, str] | None,
    ) -> None:
        """Persist a single event.

        When SQLite is available it is the authoritative ledger. File JSON/WAL
        paths are retained only for explicit non-SQLite stores and legacy tests;
        SQLite write failures are fatal because falling back would create two
        divergent sources of truth.
        """
        if self._sqlite_store is not None:
            try:
                self._sqlite_store.write_event(event_id, payload)
                self._record_persist_success(
                    event_id,
                    is_critical=self._is_critical_payload(payload),
                    mode='sqlite',
                )
                return
            except Exception as exc:
                self.stats['persist_failures'] += 1
                self._last_persist_failure_at_monotonic = time.monotonic()
                if self._recent_persist_failures is not None:
                    self._recent_persist_failures.append(time.monotonic())
                logger.error(
                    'Authoritative SQLite write failed for event %d; refusing file fallback: %s',
                    event_id,
                    exc,
                )
                raise

        filename = self._get_filename_for_id(event_id, self.user_id)
        is_critical = self._is_critical_payload(payload)

        # Critical events are written synchronously to avoid loss.
        if is_critical:
            self.stats['critical_sync_persistence'] += 1
            self._write_event_sync(filename, payload, cache_payload)
            return

        writer = self._durable_writer
        if writer:
            persisted = PersistedEvent(
                event_id=event_id,
                payload=payload,
                filename=filename,
                cache_filename=cache_payload[0] if cache_payload else None,
                cache_contents=cache_payload[1] if cache_payload else None,
            )
            if writer.enqueue(persisted):
                self._last_enqueued_event_id = event_id
                return
            self.stats['durable_enqueue_failures'] += 1

        self._write_event_sync(filename, payload, cache_payload)

    def build_cache_payload(
        self,
        current_write_page: list[dict] | None,
    ) -> tuple[str, str] | None:
        """Return ``(filename, contents)`` when a full cache page is ready."""
        if not current_write_page or len(current_write_page) < self._cache_size:
            return None
        start = current_write_page[0]['id']
        end = start + self._cache_size
        contents = json.dumps(current_write_page)
        cache_filename = self._get_filename_for_cache(start, end)
        return cache_filename, contents

    def get_health_snapshot(self) -> dict[str, Any]:
        """Return lightweight persistence-health diagnostics for recovery and ops."""
        last_success = self._last_persisted_at_monotonic
        last_failure = self._last_persist_failure_at_monotonic
        health = 'healthy'
        if last_failure is not None and (
            last_success is None or last_failure >= last_success
        ):
            health = 'degraded'
        return {
            'persistence_health': health,
            'last_confirmed_event_id': self._last_confirmed_event_id,
            'last_confirmed_critical_event_id': self._last_confirmed_critical_event_id,
            'last_enqueued_event_id': self._last_enqueued_event_id,
            'last_persistence_mode': self._last_persistence_mode,
        }

    def _process_pending_file(
        self, pending_path: str, event_path: str, events_dir: str
    ) -> tuple[int, int]:
        """Process one .pending file. Returns (recovered_delta, cleaned_delta)."""
        if self._sqlite_store is not None:
            return self._process_pending_file_to_sqlite(pending_path, event_path)
        try:
            self.file_store.read(event_path)
            # Canonical event file already exists — clean up the stale WAL marker.
            try:
                self.file_store.delete(pending_path)
                return (0, 1)
            except Exception as exc:
                logger.debug(
                    'WAL cleanup: could not delete stale .pending file %s: %s',
                    pending_path,
                    exc,
                )
                return (0, 0)
        except FileNotFoundError:
            # Canonical file missing — recover from WAL marker.
            try:
                event_json = self.file_store.read(pending_path)
                self.file_store.write(event_path, event_json)
                self.file_store.delete(pending_path)
                return (1, 0)
            except Exception as exc:
                # Recovery failed — check if the canonical file is corrupt
                # (exists but unreadable) vs truly absent.
                try:
                    self.file_store.read(event_path)
                    # Canonical exists now (race with another recovery) — clean WAL.
                    try:
                        self.file_store.delete(pending_path)
                    except Exception:
                        pass
                    return (0, 1)
                except FileNotFoundError:
                    pass  # truly absent, proceed to quarantine

                logger.error(
                    'WAL replay: UNRECOVERABLE pending file %s for session %s — '
                    'event may be lost. Error: %s. '
                    'Moving to lost_events/ for manual inspection.',
                    pending_path,
                    self.sid,
                    exc,
                )
                self._quarantine_pending_file(pending_path, events_dir)
                return (0, 0)
        except Exception:
            logger.debug(
                'WAL replay: skipping %s (read error)', pending_path, exc_info=True
            )
            return (0, 0)

    def _event_id_from_event_path(self, path: str) -> int:
        """Extract an integer event ID from an event JSON or pending path."""
        normalized = path.replace('\\', '/')
        name = os.path.basename(normalized)
        if name.endswith('.pending'):
            name = name[: -len('.pending')]
        if name.endswith('.json'):
            name = name[: -len('.json')]
        try:
            return int(name)
        except ValueError as exc:
            raise ValueError(f'Cannot extract event id from {path!r}') from exc

    def _process_pending_file_to_sqlite(
        self, pending_path: str, event_path: str
    ) -> tuple[int, int]:
        """Recover a legacy file-WAL marker into authoritative SQLite."""
        event_id = self._event_id_from_event_path(event_path)
        try:
            if self._sqlite_store.read_event(event_id) is not None:
                self.file_store.delete(pending_path)
                return (0, 1)
            event_json = self.file_store.read(pending_path)
            payload = json.loads(event_json)
            if not isinstance(payload, dict):
                raise ValueError('pending event payload is not a JSON object')
            self._sqlite_store.write_event(event_id, payload)
            self.file_store.delete(pending_path)
            return (1, 0)
        except Exception as exc:
            logger.error(
                'SQLite WAL replay failed for pending event %s in session %s: %s',
                pending_path,
                self.sid,
                exc,
            )
            raise

    def _migrate_legacy_event_files_to_sqlite(self) -> None:
        """Import legacy per-event JSON files into the authoritative SQLite ledger."""
        try:
            events_dir = get_conversation_events_dir(self.sid, self.user_id)
            all_files = self.file_store.list(events_dir)
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.debug(
                'SQLite migration: could not list legacy event dir for %s: %s',
                self.sid,
                exc,
            )
            return

        legacy_files: list[tuple[int, str]] = []
        for entry in all_files:
            normalized = self._normalize_event_path(entry, events_dir)
            if not normalized.endswith('.json'):
                continue
            if normalized.endswith('.pending') or '/event_cache/' in normalized:
                continue
            try:
                legacy_files.append(
                    (self._event_id_from_event_path(normalized), normalized)
                )
            except ValueError:
                continue

        if not legacy_files:
            return

        migrated = 0
        for event_id, path in sorted(legacy_files):
            if self._sqlite_store.read_event(event_id) is not None:
                continue
            raw = self.file_store.read(path)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f'Legacy event file {path} is not a JSON object')
            self._sqlite_store.write_event(event_id, payload)
            migrated += 1

        if migrated:
            logger.info(
                'Migrated %d legacy JSON event(s) into SQLite ledger for session %s',
                migrated,
                self.sid,
            )

    def _quarantine_pending_file(self, pending_path: str, events_dir: str) -> None:
        """Move an unrecoverable .pending file to a lost_events/ subdirectory.

        This preserves the data for post-mortem inspection without silently
        discarding it, and prevents the replay from re-attempting it on
        every startup.
        """
        try:
            lost_dir = f'{events_dir}lost_events/'
            filename = os.path.basename(pending_path.replace('\\', '/'))
            dest_path = f'{lost_dir}{filename}'
            event_json = self.file_store.read(pending_path)
            self.file_store.write(dest_path, event_json)
            self.file_store.delete(pending_path)
            logger.error(
                'WAL replay: quarantined unrecoverable pending file to %s',
                dest_path,
            )
        except Exception as quarantine_exc:
            logger.error(
                'WAL replay: could not quarantine %s: %s — file left in place',
                pending_path,
                quarantine_exc,
            )

    def _quarantine_orphan_pending(self, pending_path: str) -> None:
        """Quarantine a .pending file that couldn't be deleted after event write.

        This handles the case where the event file was successfully written but
        the .pending marker couldn't be removed (e.g., permission error on
        Windows, or antivirus interference). The orphan is moved to a lost_events/
        subdirectory to prevent it from being replayed on every startup.
        """
        try:
            pending_normalized = pending_path.replace('\\', '/')
            events_dir = get_conversation_events_dir(self.sid, self.user_id)
            lost_dir = f'{events_dir}lost_events/'
            filename = os.path.basename(pending_normalized)
            orphan_marker = f'orphan_{time.time():.0f}_{filename}'
            dest_path = f'{lost_dir}{orphan_marker}'
            try:
                event_json = self.file_store.read(pending_path)
                self.file_store.write(dest_path, event_json)
            except Exception:
                pass
            try:
                self.file_store.delete(pending_path)
            except Exception:
                pass
            logger.warning(
                'WAL: quarantined orphan .pending file to %s (original delete failed)',
                dest_path,
            )
        except Exception as quarantine_exc:
            logger.error(
                'WAL: could not quarantine orphan pending %s: %s',
                pending_path,
                quarantine_exc,
            )

    def replay_pending_events(self) -> int:
        """Scan the events directory for ``.pending`` WAL markers.

        Recovers any events left as ``.pending`` after a crash and cleans
        up stale markers whose canonical event files already exist.

        Returns:
            int: Number of events recovered from pending files.
        """
        try:
            events_dir = get_conversation_events_dir(self.sid, self.user_id)
            all_files = self.file_store.list(events_dir)
        except FileNotFoundError:
            return 0
        except Exception:
            logger.debug(
                'WAL replay: could not list events dir for %s', self.sid, exc_info=True
            )
            return 0

        pending_files = [f for f in all_files if f.endswith('.pending')]
        if not pending_files:
            return 0

        recovered, cleaned, failed = 0, 0, 0
        for pending_name in pending_files:
            pending_path = self._normalize_event_path(pending_name, events_dir)
            event_path = pending_path.removesuffix('.pending')
            r, c = self._process_pending_file(pending_path, event_path, events_dir)
            recovered += r
            cleaned += c
            if r == 0 and c == 0:
                failed += 1

        if recovered or cleaned or failed:
            level = logger.error if failed else logger.info
            level(
                'WAL replay for session %s: recovered=%d, cleaned=%d stale markers, failed=%d',
                self.sid,
                recovered,
                cleaned,
                failed,
                extra={'session_id': self.sid, 'user_id': self.user_id},
            )
        return recovered

    def close(self) -> None:
        """Shutdown durable writer and SQLite store."""
        if self._durable_writer:
            self._durable_writer.stop()
        if self._sqlite_store is not None:
            try:
                self._sqlite_store.close()
            except Exception:
                logger.debug('Error closing SQLite event store', exc_info=True)
            self._sqlite_store = None

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_event_path(raw_path: str, events_dir: str) -> str:
        """Ensure *raw_path* has the *events_dir* prefix exactly once.

        ``file_store.list()`` may return paths that already include the
        events_dir prefix, while internal construction may omit it.
        This one-liner prevents the double-prefix bug permanently.
        """
        # Normalise separators
        raw = raw_path.replace('\\', '/')
        base = events_dir.replace('\\', '/')
        if raw.startswith(base):
            return raw
        return f'{base}{raw}'

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def is_critical_payload(cls, payload: dict[str, Any]) -> bool:
        """Check if a serialized event payload is a critical control/error event."""
        return cls._is_critical_payload(payload)

    @classmethod
    def _is_critical_payload(cls, payload: dict[str, Any]) -> bool:
        action_name = payload.get('action')
        if isinstance(action_name, str):
            return action_name in cls._CRITICAL_ACTIONS
        observation_name = payload.get('observation')
        if isinstance(observation_name, str):
            return observation_name in cls._CRITICAL_OBSERVATIONS
        return False

    def _write_event_sync(
        self,
        filename: str,
        payload: dict[str, Any],
        cache_payload: tuple[str, str] | None,
    ) -> None:
        event_json = json.dumps(payload)
        json_len = len(event_json)

        # Embed an integrity checksum so corruption is detectable on read.
        payload = embed_checksum(payload)
        event_json = json.dumps(payload)
        json_len = len(event_json)

        max_event_bytes = 5 * 1024 * 1024  # 5 MB
        if json_len > max_event_bytes:
            logger.error(
                'Event JSON exceeds hard cap (%dMB): %d bytes, filename: %s — '
                'truncating large fields to fit.',
                max_event_bytes // (1024 * 1024),
                json_len,
                filename,
                extra={
                    'user_id': self.user_id,
                    'session_id': self.sid,
                    'size': json_len,
                },
            )
            _truncate_payload(payload, max_event_bytes)
            event_json = json.dumps(payload)
        elif json_len > 1_000_000:
            logger.warning(
                'Saving event JSON over 1MB: %s bytes, filename: %s',
                json_len,
                filename,
                extra={
                    'user_id': self.user_id,
                    'session_id': self.sid,
                    'size': json_len,
                },
            )

        try:
            pending_file = filename + '.pending'
            try:
                self.file_store.write(pending_file, event_json)
            except Exception as exc:
                logger.warning(
                    'WAL: could not write .pending marker %s: %s',
                    pending_file,
                    exc,
                )

            self.file_store.write(filename, event_json)

            try:
                self.file_store.delete(pending_file)
            except Exception as exc:
                logger.warning(
                    'WAL: could not remove .pending marker %s: %s',
                    pending_file,
                    exc,
                )
                self._quarantine_orphan_pending(pending_file)
            event_id = payload.get('id')
            if isinstance(event_id, int):
                self._record_persist_success(
                    event_id,
                    is_critical=self._is_critical_payload(payload),
                    mode='sync',
                )
        except Exception as exc:  # pragma: no cover
            self.stats['persist_failures'] += 1
            self._last_persist_failure_at_monotonic = time.monotonic()
            if self._recent_persist_failures is not None:
                self._recent_persist_failures.append(time.monotonic())
            logger.error(
                'Failed to persist event file %s for %s: %s',
                filename,
                self.sid,
                exc,
                extra={'session_id': self.sid, 'user_id': self.user_id},
            )
            return

        if cache_payload:
            cache_filename, cache_contents = cache_payload
            try:
                self.file_store.write(cache_filename, cache_contents)
            except Exception as exc:  # pragma: no cover
                self.stats['cache_write_failures'] += 1
                logger.debug(
                    'Cache page write failed for %s (%s): %s',
                    self.sid,
                    cache_filename,
                    exc,
                )

    @property
    def durable_writer(self) -> DurableEventWriter | None:
        """Expose durable writer for stats aggregation."""
        return self._durable_writer

    def _record_persist_success(
        self,
        event_id: int,
        *,
        is_critical: bool,
        mode: str,
    ) -> None:
        self._last_confirmed_event_id = event_id
        if is_critical:
            self._last_confirmed_critical_event_id = event_id
        self._last_persisted_at_monotonic = time.monotonic()
        self._last_persistence_mode = mode


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _truncate_payload(payload: dict[str, Any], max_bytes: int) -> None:
    """Truncate the largest string values in *payload* in-place.

    Walks the top-level and one nested level, finds the longest string
    values, and truncates them until the estimated JSON size falls below
    *max_bytes*.
    """
    trunc_marker = '\n\n[… truncated by Grinta — event exceeded size cap …]'

    def _string_fields(d: dict, prefix: str = '') -> list[tuple[str, dict, str]]:
        results: list[tuple[str, dict, str]] = []
        for k, v in d.items():
            if isinstance(v, str):
                results.append((f'{prefix}{k}', d, k))
            elif isinstance(v, dict):
                results.extend(_string_fields(v, f'{prefix}{k}.'))
        return results

    fields = _string_fields(payload)
    fields.sort(key=lambda t: len(t[1][t[2]]), reverse=True)

    for _path, parent, key in fields:
        current_estimate = len(json.dumps(payload))
        if current_estimate <= max_bytes:
            break
        val = parent[key]
        if len(val) > 10_000:
            keep = max_bytes // (len(fields) or 1)
            keep = max(keep, 2_000)
            half = keep // 2
            parent[key] = val[:half] + trunc_marker + val[-half:]
