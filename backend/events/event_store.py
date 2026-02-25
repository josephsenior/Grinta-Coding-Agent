"""File-backed event store implementation with caching helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
import time

from backend.core.logger import forge_logger as logger
from backend.events.event_store_abc import EventStoreABC
from backend.events.serialization.event import event_from_dict
from backend.storage.locations import (
    get_conversation_dir,
    get_conversation_event_filename,
    get_conversation_events_dir,
)
from backend.utils.shutdown_listener import should_continue

if TYPE_CHECKING:
    from backend.events.event import Event, EventSource
    from backend.events.event_filter import EventFilter
    from backend.storage.files import FileStore


@dataclass(frozen=True)
class _CachePage:
    events: list[dict[str, Any]] | None
    start: int
    end: int
    __test__ = False

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
    __test__ = False

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
        events = []
        try:
            events_dir = get_conversation_events_dir(self.sid, self.user_id)
            events = self.file_store.list(events_dir)
        except FileNotFoundError:
            logger.debug("No events found for session %s at %s", self.sid, events_dir)
        if not events:
            return 0
        max_id = -1
        for event_str in events:
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

        cache_page = _DUMMY_PAGE
        num_results = 0

        for index in range(start_id, end_id, step):
            if not should_continue():
                return

            if not cache_page.covers(index):
                cache_page = self._load_cache_page_for_index(index)

            try:
                event = self._get_event_from_cache_or_storage(index, cache_page)
            except (json.JSONDecodeError, ValueError) as exc:
                # Corrupt or partially-written event file; stop iteration to avoid
                # taking down long-running sessions.
                logger.warning(
                    "Stopping event search for %s at id=%s due to unreadable event: %s",
                    self.sid,
                    index,
                    exc,
                    extra={"session_id": self.sid, "event_id": index},
                )
                return
            if event is None:
                continue
            if event_filter and not event_filter.include(event):
                continue

            yield event
            num_results += 1
            if limit and limit <= num_results:
                return

    def get_event(self, event_id: int) -> Event:
        """Get event by ID from persistent storage.

        Args:
            event_id: Event ID to retrieve

        Returns:
            Event object

        Raises:
            FileNotFoundError: If event doesn't exist

        """
        filename = self._get_filename_for_id(event_id, self.user_id)
        last_error: Exception | None = None
        for _ in range(5):
            try:
                content = self.file_store.read(filename)
                data = json.loads(content)
                return event_from_dict(data)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                time.sleep(0.01)
        if last_error:
            raise last_error
        content = self.file_store.read(filename)
        data = json.loads(content)
        return event_from_dict(data)

    def get_latest_event(self) -> Event:
        """Get most recent event from storage.

        Returns:
            Latest event object

        """
        return self.get_event(self.cur_id - 1)

    def get_latest_event_id(self) -> int:
        """Get ID of most recent event.

        Returns:
            Latest event ID

        """
        return self.cur_id - 1

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
        return f"{get_conversation_dir(self.sid, self.user_id)}event_cache/{start}-{end}.json"

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
                "Ignoring corrupt event cache page %s for %s (%s-%s): %s",
                cache_filename,
                self.sid,
                start,
                end,
                exc,
                extra={"session_id": self.sid},
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
            return int(filename.split("/")[-1].split(".")[0])
        except ValueError:
            logger.warning("get id from filename (%s) failed.", filename)
            return -1
