"""File-backed event store implementation with caching helpers."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.ledger.event.event_store_abc import EventStoreABC
from backend.ledger.serialization.event import event_from_dict
from backend.persistence.locations import (
    get_conversation_dir,
    get_conversation_event_filename,
    get_conversation_events_dir,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event, EventSource
    from backend.ledger.event.event_filter import EventFilter
    from backend.persistence.files import FileStore

_SEARCH_ABORT = object()


def _verify_event_checksum(data: dict, event_id: int) -> None:
    """Verify integrity checksum if present; raise ValueError on mismatch."""
    from backend.ledger.integrity import verify_event_integrity

    if not verify_event_integrity(data, event_id):
        raise ValueError(
            f'Event {event_id}: integrity checksum mismatch — possible corruption'
        )


def _file_store_fs_root(file_store: FileStore) -> str | None:
    """Sync with :func:`backend.ledger.persistence._file_store_fs_root`."""
    from backend.ledger.persistence import _file_store_fs_root as _root

    return _root(file_store)


@dataclass(frozen=True)
class _CachePage:
    events: list[dict[str, Any]] | None
    start: int
    end: int

    def covers(self, global_index: int) -> bool:
        """Check if this cache page contains the given event index.

        Args:
            global_index: Global event index to check

        Returns:
            True if index is in this cache page

        """
        return False if global_index < self.start else global_index < self.end

    def get_event(self, global_index: int) -> Event | None:
        """Get event from this cache page by global index.

        Args:
            global_index: Global event index

        Returns:
            Event object or None if not in cache

        """
        if not self.events:
            return None
        local_index = global_index - self.start
        return event_from_dict(self.events[local_index])


_DUMMY_PAGE = _CachePage(None, 1, -1)


@dataclass
class EventStore(EventStoreABC):
    """A stored list of events backing a conversation."""

    sid: str
    file_store: FileStore
    user_id: str | None
    cache_size: int = 25
    _cur_id: int | None = None

    def __post_init__(self) -> None:
        """Initialize the optional SQLite event store."""
        import os

        self._sqlite_store: Any = None
        if str(os.getenv('APP_SQLITE_EVENTS', 'true')).lower() in ('1', 'true', 'yes'):
            try:
                from backend.persistence.sqlite_event_store import SQLiteEventStore

                fs_root = _file_store_fs_root(self.file_store)
                if fs_root:
                    events_dir = get_conversation_events_dir(self.sid, self.user_id)
                    db_path = os.path.join(
                        fs_root,
                        events_dir,
                        'events.db',
                    )
                    store = SQLiteEventStore(db_path=db_path)
                    repaired = store.repair_event_checksums()
                    if repaired:
                        logger.info(
                            'Repaired %d SQLite event checksum(s) for session %s at init',
                            repaired,
                            self.sid,
                        )
                    if store.check_integrity(verify_checksums=True):
                        self._sqlite_store = store
                    else:
                        store.close()
                        raise RuntimeError(
                            'Authoritative SQLite event store for session '
                            f'{self.sid} failed integrity check'
                        )
            except Exception as exc:
                raise RuntimeError(
                    f'Failed to init authoritative SQLite store for session {self.sid}'
                ) from exc

    def close(self) -> None:
        """Release the optional SQLite accelerator, if it is open."""
        if self._sqlite_store is not None:
            try:
                self._sqlite_store.close()
            except Exception:
                logger.debug(
                    'Error closing EventStore SQLite accelerator', exc_info=True
                )
            self._sqlite_store = None

    @property
    def cur_id(self) -> int:
        """Lazy calculated property for the current event ID."""
        if self._cur_id is None:
            self._cur_id = self._calculate_cur_id()
        return self._cur_id

    @cur_id.setter
    def cur_id(self, value: int) -> None:
        """Setter for cur_id to allow updates."""
        self._cur_id = value

    def _calculate_cur_id(self) -> int:
        """Calculate the current event ID based on file system content."""
        if getattr(self, '_sqlite_store', None) is not None:
            return self._sqlite_store.max_id() + 1

        max_id = -1
        events = []
        try:
            events_dir = get_conversation_events_dir(self.sid, self.user_id)
            events = self.file_store.list(events_dir)
        except FileNotFoundError:
            if max_id == -1:
                logger.debug(
                    'No events found for session %s at %s', self.sid, events_dir
                )

        if not events and max_id == -1:
            return 0

        for event_str in events:
            if (
                event_str == 'events.db'
                or event_str.endswith('.db-wal')
                or event_str.endswith('.db-shm')
            ):
                continue
            event_id = self._get_id_from_filename(event_str)
            max_id = max(event_id, max_id)
        return max_id + 1

    def _normalize_search_range(
        self, start_id: int, end_id: int | None
    ) -> tuple[int, int]:
        """Normalize the search range based on current ID and end_id."""
        if end_id is None:
            end_id = self.cur_id
        else:
            end_id += 1
        return start_id, end_id

    def _setup_reverse_search(
        self, start_id: int, end_id: int, reverse: bool
    ) -> tuple[int, int, int]:
        """Set up parameters for reverse search if needed."""
        if reverse:
            step = -1
            start_id, end_id = (end_id, start_id)
            start_id -= 1
            end_id -= 1
        else:
            step = 1
        return start_id, end_id, step

    def _get_event_from_cache_or_storage(
        self, index: int, cache_page: _CachePage
    ) -> Event | None:
        """Get event from cache or storage."""
        event = cache_page.get_event(index)
        if event is not None:
            return event

        for _ in range(5):
            try:
                return self.get_event(index)
            except FileNotFoundError:
                time.sleep(0.01)
        try:
            return self.get_event(index)
        except FileNotFoundError:
            return None

    def search_events(
        self,
        start_id: int = 0,
        end_id: int | None = None,
        reverse: bool = False,
        filter: EventFilter | None = None,
        limit: int | None = None,
    ) -> Iterable[Event]:
        """Retrieve events from the event stream, optionally filtering out events of a given type.

        and events marked as hidden.

        Args:
            start_id: The ID of the first event to retrieve. Defaults to 0.
            end_id: The ID of the last event to retrieve. Defaults to the last event in the stream.
            reverse: Whether to retrieve events in reverse order. Defaults to False.
            filter: EventFilter to use
            limit: Maximum number of events to retrieve. Defaults to None (no limit).

        Yields:
            Events from the stream that match the criteria.

        """
        event_filter = filter
        start_id, end_id = self._normalize_search_range(start_id, end_id)
        start_id, end_id, step = self._setup_reverse_search(start_id, end_id, reverse)

        if self._can_use_sqlite_batch(reverse, event_filter, step):
            batch_events = self._search_sqlite_batch(start_id, end_id, limit)
            if batch_events:
                yield from batch_events
                return

        yield from self._search_event_files(start_id, end_id, step, event_filter, limit)

    def _can_use_sqlite_batch(
        self, reverse: bool, event_filter: EventFilter | None, step: int
    ) -> bool:
        return (
            getattr(self, '_sqlite_store', None) is not None
            and not reverse
            and event_filter is None
            and step == 1
        )

    def _search_sqlite_batch(
        self, start_id: int, end_id: int, limit: int | None
    ) -> list[Event]:
        try:
            batch = self._sqlite_store.list_events(
                start_id=start_id,
                end_id=end_id,
                limit=limit,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug(
                'SQLite batch read failed for %s; falling back to per-event scan: %s',
                self.sid,
                exc,
            )
            return []
        events: list[Event] = []
        for data in batch:
            try:
                event = event_from_dict(data)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning(
                    'Skipping corrupt SQLite event in batch for %s: %s',
                    self.sid,
                    exc,
                )
                continue
            events.append(event)
        return events

    def _search_event_files(
        self,
        start_id: int,
        end_id: int,
        step: int,
        event_filter: EventFilter | None,
        limit: int | None,
    ) -> Iterable[Event]:
        cache_page = _DUMMY_PAGE
        num_results = 0
        corrupt_seen = 0
        max_corrupt = 5

        for index in range(start_id, end_id, step):
            if not cache_page.covers(index):
                cache_page = self._load_cache_page_for_index(index)

            load_result = self._load_event_with_corruption_guard(
                index, cache_page, corrupt_seen, max_corrupt
            )
            if load_result is _SEARCH_ABORT:
                return
            if not isinstance(load_result, tuple):
                return
            event_obj, corrupt_seen = load_result
            if event_obj is None:
                continue
            if event_filter and not event_filter.include(event_obj):
                continue

            yield event_obj
            num_results += 1
            if limit and limit <= num_results:
                return

    def _load_event_with_corruption_guard(
        self, index: int, cache_page: Any, corrupt_seen: int, max_corrupt: int
    ) -> tuple[Event | None, int] | object:
        try:
            event = self._get_event_from_cache_or_storage(index, cache_page)
        except (json.JSONDecodeError, ValueError) as exc:
            corrupt_seen += 1
            logger.warning(
                'Skipping corrupt event id=%s in search for %s: %s (skipped %s/%s)',
                index,
                self.sid,
                exc,
                corrupt_seen,
                max_corrupt,
                extra={'session_id': self.sid, 'event_id': index},
            )
            if corrupt_seen >= max_corrupt:
                logger.error(
                    'Aborting event search for %s: %s consecutive corrupt events',
                    self.sid,
                    max_corrupt,
                )
                return _SEARCH_ABORT
            return None, corrupt_seen
        return event, corrupt_seen

    def get_event(self, event_id: int) -> Event:
        """Get event by ID from persistent storage.

        Args:
            event_id: Event ID to retrieve

        Returns:
            Event object

        Raises:
            FileNotFoundError: If event doesn't exist

        """
        if getattr(self, '_sqlite_store', None) is not None:
            data = self._sqlite_store.read_event(event_id)
            if data is not None:
                return event_from_dict(data)
            raise FileNotFoundError(
                f'Event {event_id} missing from authoritative SQLite ledger'
            )

        filename = self._get_filename_for_id(event_id, self.user_id)
        last_error: Exception | None = None
        for _ in range(5):
            try:
                content = self.file_store.read(filename)
                data = json.loads(content)
                _verify_event_checksum(data, event_id)
                return event_from_dict(data)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                time.sleep(0.01)
        if last_error:
            raise last_error
        content = self.file_store.read(filename)
        data = json.loads(content)
        _verify_event_checksum(data, event_id)
        return event_from_dict(data)

    def get_latest_event(self) -> Event:
        """Get most recent event from storage.

        Returns:
            Latest event object

        Raises:
            ValueError: If no events exist in the stream
        """
        latest_id = self.cur_id - 1
        if latest_id < 0:
            raise ValueError('No events in stream — cannot get latest event.')
        return self.get_event(latest_id)

    def get_latest_event_id(self) -> int:
        """Get ID of most recent event.

        Returns:
            Latest event ID, or -1 if no events exist

        """
        cur = self.cur_id
        if cur <= 0:
            return -1
        return cur - 1

    def filtered_events_by_source(self, source: EventSource) -> Iterable[Event]:
        """Filter events by source (USER, AGENT, ENVIRONMENT, etc.).

        Args:
            source: Event source to filter by

        Yields:
            Events matching the source

        """
        for event in self.search_events():
            if event.source == source:
                yield event

    def _get_filename_for_id(self, event_id: int, user_id: str | None) -> str:
        return get_conversation_event_filename(self.sid, event_id, user_id)

    def _get_filename_for_cache(self, start: int, end: int) -> str:
        return f'{get_conversation_dir(self.sid, self.user_id)}event_cache/{start}-{end}.json'

    def _load_cache_page(self, start: int, end: int) -> _CachePage:
        """Read a page from the cache. Reading individual events is slow when there are a lot of them, so we use pages."""
        cache_filename = self._get_filename_for_cache(start, end)
        try:
            content = self.file_store.read(cache_filename)
            events = json.loads(content)
        except FileNotFoundError:
            events = None
        except (json.JSONDecodeError, ValueError) as exc:
            # Cache corruption should never take down the event stream.
            logger.warning(
                'Ignoring corrupt event cache page %s for %s (%s-%s): %s',
                cache_filename,
                self.sid,
                start,
                end,
                exc,
                extra={'session_id': self.sid},
            )
            events = None
        return _CachePage(events, start, end)

    def _load_cache_page_for_index(self, index: int) -> _CachePage:
        offset = index % self.cache_size
        index -= offset
        return self._load_cache_page(index, index + self.cache_size)

    @staticmethod
    def _get_id_from_filename(filename: str) -> int:
        try:
            return int(filename.split('/')[-1].split('.')[0])
        except (ValueError, IndexError):
            logger.debug('get id from filename (%s) failed.', filename)
            return -1

    def prune_old_events(self, keep_recent: int = 1000) -> int:
        """Delete persisted event files older than the most recent *keep_recent* events.

        Returns the number of events pruned.  Cache pages for pruned events
        are also deleted.  This is a best-effort operation — failures are
        logged but do not raise.
        """
        from backend.persistence.locations import get_conversation_events_dir

        cutoff_id = self._compute_prune_cutoff(keep_recent)
        if cutoff_id <= 0:
            return 0

        events_dir = get_conversation_events_dir(self.sid, self.user_id)
        pruned = self._prune_event_files(events_dir, cutoff_id)
        self._prune_stale_cache_pages(events_dir, cutoff_id)

        if pruned > 0:
            logger.info(
                'prune_old_events: removed %d events older than id %d for session %s',
                pruned,
                cutoff_id,
                self.sid,
            )
        return pruned

    def _compute_prune_cutoff(self, keep_recent: int) -> int:
        try:
            latest_id = self.get_latest_event_id()
        except Exception:
            return 0
        if latest_id <= keep_recent:
            return 0
        return latest_id - keep_recent

    def _prune_event_files(self, events_dir: str, cutoff_id: int) -> int:
        pruned = 0
        try:
            entries = self.file_store.list(events_dir)
        except Exception:
            return 0
        for entry in entries:
            if not entry.endswith('.json'):
                continue
            eid = self._get_id_from_filename(entry)
            if eid < 0 or eid >= cutoff_id:
                continue
            try:
                self.file_store.delete(f'{events_dir}{entry}')
                pruned += 1
            except Exception:
                logger.debug(
                    'prune_old_events: could not delete %s', entry, exc_info=True
                )
        return pruned

    def _prune_stale_cache_pages(self, events_dir: str, cutoff_id: int) -> None:
        try:
            cache_dir = f'{events_dir}event_cache/'
            cache_entries = self.file_store.list(cache_dir)
            for entry in cache_entries:
                if not entry.endswith('.json'):
                    continue
                page_end = self._parse_cache_page_end(entry)
                if page_end is not None and page_end <= cutoff_id:
                    try:
                        self.file_store.delete(f'{cache_dir}{entry}')
                    except Exception:
                        pass
        except Exception:
            pass

    @staticmethod
    def _parse_cache_page_end(entry: str) -> int | None:
        try:
            parts = entry.replace('.json', '').split('-')
            return int(parts[1])
        except (ValueError, IndexError):
            return None


__all__ = ['EventStore']
