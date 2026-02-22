"""HTTP-backed event store implementation for remote conversations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
from fastapi import status

from backend.events.event_store_abc import EventStoreABC
from backend.events.serialization.event import event_from_dict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from backend.events.event import Event
    from backend.events.event_filter import EventFilter


@dataclass
class NestedEventStore(EventStoreABC):
    """A stored list of events backing a conversation."""

    base_url: str
    sid: str
    user_id: str | None

    def _build_search_params(
        self,
        start_cursor: int,
        end_cursor: int | None,
        reverse: bool,
        limit: int | None,
    ) -> dict[str, int | bool]:
        """Build search parameters for the API request."""
        search_params: dict[str, int | bool] = {
            "start_id": start_cursor,
            "reverse": reverse,
        }
        if reverse and end_cursor is not None:
            search_params["end_id"] = end_cursor
        if limit is not None:
            search_params["limit"] = min(100, limit)
        return search_params

    def _make_api_request(self, search_params: dict[str, int | bool]) -> dict | None:
        """Make API request and return parsed response."""
        search_str = urlencode(search_params)
        url = f"{self.base_url}/events?{search_str}"
        headers: dict[str, str] = {}
        response = httpx.get(url, headers=headers)
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return None
        return response.json()

    def _process_event(
        self,
        event: Event,
        end_id: int | None,
        filter: EventFilter | None,
        limit: int | None,
    ) -> tuple[bool, bool]:
        """Process a single event and return (should_yield, should_stop)."""
        if end_id == event.id:
            return (
                (True, True) if not filter or filter.include(event) else (False, True)
            )
        if filter and filter.exclude(event):
            return False, False

        if limit is not None:
            limit -= 1
            if limit <= 0:
                return True, True

        return True, False

    def _update_cursors(
        self,
        reverse: bool,
        page_min_id: int | None,
        forward_next_start: int,
        start_cursor: int,
    ) -> tuple[int, int | None]:
        """Update cursors for next iteration."""
        if reverse and page_min_id is not None:
            return start_cursor, page_min_id - 1
        if not reverse:
            return forward_next_start, None
        return start_cursor, None

    def search_events(
        self,
        start_id: int = 0,
        end_id: int | None = None,
        reverse: bool = False,
        filter: EventFilter | None = None,
        limit: int | None = None,
    ) -> Iterable[Event]:
        """Search for events with pagination and filtering."""
        start_cursor = start_id
        end_cursor: int | None = None

        while True:
            # Build search parameters and make API request
            search_params = self._build_search_params(
                start_cursor, end_cursor, reverse, limit
            )
            result_set = self._make_api_request(search_params)

            if result_set is None:
                return

            # Process events in the current page
            page_min_id: int | None = None
            forward_next_start = start_cursor

            for result in result_set["events"]:
                event = event_from_dict(result)

                # Update cursors based on direction
                if reverse:
                    page_min_id = (
                        event.id if page_min_id is None else min(page_min_id, event.id)
                    )
                else:
                    forward_next_start = max(forward_next_start, event.id + 1)

                # Process event and check if we should yield/stop
                should_yield, should_stop = self._process_event(
                    event, end_id, filter, limit
                )

                if should_yield:
                    yield event

                if should_stop:
                    return

            # Update cursors for next iteration
            start_cursor, end_cursor = self._update_cursors(
                reverse, page_min_id, forward_next_start, start_cursor
            )

            # Check if there are more pages
            if not result_set["has_more"]:
                return

    def get_event(self, id: int) -> Event:
        """Get event by ID from nested event store.

        Args:
            id: Event ID to retrieve

        Returns:
            Event object

        Raises:
            FileNotFoundError: If event not found

        """
        if events := list(self.search_events(start_id=id, limit=1)):
            return events[0]
        msg = "no_event"
        raise FileNotFoundError(msg)

    def get_latest_event(self) -> Event:
        """Get most recent event from nested store.

        Returns:
            Latest event object

        Raises:
            FileNotFoundError: If no events

        """
        if events := list(self.search_events(reverse=True, limit=1)):
            return events[0]
        msg = "no_event"
        raise FileNotFoundError(msg)

    def get_latest_event_id(self) -> int:
        """Get ID of most recent event.

        Returns:
            Latest event ID

        """
        event = self.get_latest_event()
        return event.id

    __test__ = False
