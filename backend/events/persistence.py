"""Event persistence with WAL crash-recovery and optional SQLite accelerator.

Encapsulates file-based event writing, write-ahead log markers, cache page
management, and the optional durable async writer.  Used as a composition
helper by :class:`~backend.events.stream.EventStream`.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar

from backend.adapters import json
from backend.core.logger import FORGE_logger as logger
from backend.events.durable_writer import DurableEventWriter, PersistedEvent
from backend.storage.locations import get_conversation_events_dir

if TYPE_CHECKING:
    from backend.storage import FileStore


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
        "change_agent_state",
        "finish",
        "reject",
    }
    _CRITICAL_OBSERVATIONS: ClassVar[set[str]] = {
        "error",
        "agent_state_changed",
        "user_rejected",
    }

    @classmethod
    def is_critical_event(cls, event: Any) -> bool:
        """Check whether an Event instance represents a critical control/error event."""
        action_name = getattr(event, "action", None)
        if isinstance(action_name, str):
            return action_name in cls._CRITICAL_ACTIONS
        observation_name = getattr(event, "observation", None)
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
        self.stats: dict[str, int] = {
            "persist_failures": 0,
            "cache_write_failures": 0,
            "critical_sync_persistence": 0,
            "durable_enqueue_failures": 0,
        }

        # Optional SQLite accelerator
        self._sqlite_store: Any = None
        if str(os.getenv("FORGE_SQLITE_EVENTS", "false")).lower() in (
            "1",
            "true",
            "yes",
        ):
            try:
                from backend.storage.sqlite_event_store import SQLiteEventStore

                events_dir = get_conversation_events_dir(sid, user_id)
                db_path = os.path.join(
                    file_store.get_base_path()
                    if hasattr(file_store, "get_base_path")
                    else ".",
                    events_dir,
                    "events.db",
                )
                self._sqlite_store = SQLiteEventStore(db_path=db_path)
                logger.info(
                    "SQLite event accelerator enabled for session %s",
                    sid,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to initialise SQLite event store, using file-based fallback: %s",
                    exc,
                )
                self._sqlite_store = None

        # Async durable writer
        self._durable_writer: DurableEventWriter | None = None
        if async_write:
            try:
                self._durable_writer = DurableEventWriter(file_store)
                self._durable_writer.start()
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Failed to start DurableEventWriter, falling back to sync persistence: %s",
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
        """Persist a single event, choosing the fastest available path."""
        # SQLite accelerator — fast single-write, bypass filesystem entirely
        if self._sqlite_store is not None:
            try:
                self._sqlite_store.write_event(event_id, payload)
                return
            except Exception as exc:
                logger.warning(
                    "SQLite write failed for event %d, falling back to file: %s",
                    event_id,
                    exc,
                )

        filename = self._get_filename_for_id(event_id, self.user_id)
        is_critical = self._is_critical_payload(payload)

        # Critical events are written synchronously to avoid loss.
        if is_critical:
            self.stats["critical_sync_persistence"] += 1
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
                return
            self.stats["durable_enqueue_failures"] += 1

        self._write_event_sync(filename, payload, cache_payload)

    def build_cache_payload(
        self,
        current_write_page: list[dict] | None,
    ) -> tuple[str, str] | None:
        """Return ``(filename, contents)`` when a full cache page is ready."""
        if not current_write_page or len(current_write_page) < self._cache_size:
            return None
        start = current_write_page[0]["id"]
        end = start + self._cache_size
        contents = json.dumps(current_write_page)
        cache_filename = self._get_filename_for_cache(start, end)
        return cache_filename, contents

    def replay_pending_events(self) -> None:
        """Scan the events directory for ``.pending`` WAL markers.

        Recovers any events left as ``.pending`` after a crash and cleans
        up stale markers whose canonical event files already exist.
        """
        try:
            events_dir = get_conversation_events_dir(self.sid, self.user_id)
            all_files = self.file_store.list(events_dir)
        except FileNotFoundError:
            return
        except Exception:
            logger.debug(
                "WAL replay: could not list events dir for %s",
                self.sid,
                exc_info=True,
            )
            return

        pending_files = [f for f in all_files if f.endswith(".pending")]
        if not pending_files:
            return

        recovered = 0
        cleaned = 0
        for pending_name in pending_files:
            # Canonical path: file_store.list() may return paths that
            # already include the events_dir prefix — normalize to
            # avoid double-prefixing.
            pending_path = self._normalize_event_path(pending_name, events_dir)
            event_path = pending_path.removesuffix(".pending")

            try:
                self.file_store.read(event_path)
                # Event exists — stale marker
                try:
                    self.file_store.delete(pending_path)
                    cleaned += 1
                except Exception as exc:
                    logger.debug(
                        "WAL cleanup: could not delete stale .pending file %s: %s",
                        pending_path,
                        exc,
                    )
            except FileNotFoundError:
                try:
                    event_json = self.file_store.read(pending_path)
                    self.file_store.write(event_path, event_json)
                    self.file_store.delete(pending_path)
                    recovered += 1
                except Exception as exc:
                    logger.warning(
                        "WAL replay: failed to recover %s for session %s: %s",
                        pending_path,
                        self.sid,
                        exc,
                    )
            except Exception:
                logger.debug(
                    "WAL replay: skipping %s (read error)",
                    pending_path,
                    exc_info=True,
                )

        if recovered or cleaned:
            logger.info(
                "WAL replay for session %s: recovered=%d, cleaned=%d stale markers",
                self.sid,
                recovered,
                cleaned,
                extra={"session_id": self.sid, "user_id": self.user_id},
            )

    def close(self) -> None:
        """Shutdown durable writer and SQLite store."""
        if self._durable_writer:
            self._durable_writer.stop()
        if self._sqlite_store is not None:
            try:
                self._sqlite_store.close()
            except Exception:
                logger.debug("Error closing SQLite event store", exc_info=True)
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
        raw = raw_path.replace("\\", "/")
        base = events_dir.replace("\\", "/")
        if raw.startswith(base):
            return raw
        return f"{base}{raw}"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def is_critical_payload(cls, payload: dict[str, Any]) -> bool:
        """Check if a serialized event payload is a critical control/error event."""
        return cls._is_critical_payload(payload)

    @classmethod
    def _is_critical_payload(cls, payload: dict[str, Any]) -> bool:
        action_name = payload.get("action")
        if isinstance(action_name, str):
            return action_name in cls._CRITICAL_ACTIONS
        observation_name = payload.get("observation")
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

        max_event_bytes = 5 * 1024 * 1024  # 5 MB
        if json_len > max_event_bytes:
            logger.error(
                "Event JSON exceeds hard cap (%dMB): %d bytes, filename: %s — "
                "truncating large fields to fit.",
                max_event_bytes // (1024 * 1024),
                json_len,
                filename,
                extra={
                    "user_id": self.user_id,
                    "session_id": self.sid,
                    "size": json_len,
                },
            )
            _truncate_payload(payload, max_event_bytes)
            event_json = json.dumps(payload)
        elif json_len > 1_000_000:
            logger.warning(
                "Saving event JSON over 1MB: %s bytes, filename: %s",
                json_len,
                filename,
                extra={
                    "user_id": self.user_id,
                    "session_id": self.sid,
                    "size": json_len,
                },
            )

        try:
            pending_file = filename + ".pending"
            try:
                self.file_store.write(pending_file, event_json)
            except Exception as exc:
                logger.debug(
                    "WAL: could not write .pending marker %s: %s",
                    pending_file,
                    exc,
                )

            self.file_store.write(filename, event_json)

            try:
                self.file_store.delete(pending_file)
            except Exception as exc:
                logger.debug(
                    "WAL: could not remove .pending marker %s: %s",
                    pending_file,
                    exc,
                )
        except Exception as exc:  # pragma: no cover
            self.stats["persist_failures"] += 1
            if self._recent_persist_failures is not None:
                self._recent_persist_failures.append(time.monotonic())
            logger.error(
                "Failed to persist event file %s for %s: %s",
                filename,
                self.sid,
                exc,
                extra={"session_id": self.sid, "user_id": self.user_id},
            )
            return

        if cache_payload:
            cache_filename, cache_contents = cache_payload
            try:
                self.file_store.write(cache_filename, cache_contents)
            except Exception as exc:  # pragma: no cover
                self.stats["cache_write_failures"] += 1
                logger.debug(
                    "Cache page write failed for %s (%s): %s",
                    self.sid,
                    cache_filename,
                    exc,
                )

    @property
    def durable_writer(self) -> DurableEventWriter | None:
        """Expose durable writer for stats aggregation."""
        return self._durable_writer


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _truncate_payload(payload: dict[str, Any], max_bytes: int) -> None:
    """Truncate the largest string values in *payload* in-place.

    Walks the top-level and one nested level, finds the longest string
    values, and truncates them until the estimated JSON size falls below
    *max_bytes*.
    """
    trunc_marker = "\n\n[… truncated by Forge — event exceeded size cap …]"

    def _string_fields(d: dict, prefix: str = "") -> list[tuple[str, dict, str]]:
        results: list[tuple[str, dict, str]] = []
        for k, v in d.items():
            if isinstance(v, str):
                results.append((f"{prefix}{k}", d, k))
            elif isinstance(v, dict):
                results.extend(_string_fields(v, f"{prefix}{k}."))
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
