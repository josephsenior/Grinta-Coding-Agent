"""Filtering utilities for querying App event streams."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.ledger.serialization.event import event_to_dict

if TYPE_CHECKING:
    from backend.ledger.event import Event


@dataclass
class EventFilter:
    """A filter for Event objects in the event stream.

    EventFilter provides a flexible way to filter events based on various criteria
    such as event type, source, date range, and content. It can be used to include
    or exclude events from search results based on the specified criteria.

    Attributes:
        exclude_hidden: Whether to exclude events marked as hidden. Defaults to False.
        query: Text string to search for in event content. Case-insensitive. Defaults to None.
        include_types: Tuple of Event types to include. Only events of these types will pass the filter.
            Defaults to None (include all types).
        exclude_types: Tuple of Event types to exclude. Events of these types will be filtered out.
            Defaults to None (exclude no types).
        source: Filter by event source (e.g., 'agent', 'user', 'environment'). Defaults to None.
        start_date: ISO format date string. Only events after this date will pass the filter.
            Defaults to None.
        end_date: ISO format date string. Only events before this date will pass the filter.
            Defaults to None.

    """

    exclude_hidden: bool = False
    query: str | None = None
    include_types: tuple[type[Event], ...] | None = None
    exclude_types: tuple[type[Event], ...] | None = None
    source: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    def include(self, event: Event) -> bool:
        """Determine if an event should be included based on the filter criteria.

        This method checks if the given event matches all the filter criteria.
        If any criterion fails, the event is excluded.

        Args:
            event: The Event object to check against the filter criteria.

        Returns:
            bool: True if the event passes all filter criteria and should be included,
                  False otherwise.

        """
        # Check type filters
        if not self._check_type_filters(event):
            return False

        # Check source filter
        if not self._check_source_filter(event):
            return False

        # Check date filters
        if not self._check_date_filters(event):
            return False

        # Check hidden filter
        if not self._check_hidden_filter(event):
            return False

        # Check query filter
        return bool(self._check_query_filter(event))

    def _check_type_filters(self, event: Event) -> bool:
        """Check if event passes type-based filters."""
        # Check include types
        if self.include_types and not isinstance(event, self.include_types):
            return False

        # Check exclude types
        return self.exclude_types is None or not isinstance(event, self.exclude_types)

    def _check_source_filter(self, event: Event) -> bool:
        """Check if event passes source filter."""
        return not self.source or (
            event.source is not None and event.source.value == self.source
        )

    def _check_date_filters(self, event: Event) -> bool:
        """Check if event passes date-based filters."""
        if event.timestamp is None:
            return True

        # Check start date
        if self.start_date and event.timestamp < self.start_date:
            return False

        # Check end date
        return not self.end_date or event.timestamp <= self.end_date

    def _check_hidden_filter(self, event: Event) -> bool:
        """Check if event passes hidden filter."""
        return not self.exclude_hidden or not getattr(event, 'hidden', False)

    def _check_query_filter(self, event: Event) -> bool:
        """Check if event passes query filter."""
        if not self.query:
            return True

        event_dict = event_to_dict(event)
        event_str = json.dumps(event_dict).lower()
        return self.query.lower() in event_str

    def exclude(self, event: Event) -> bool:
        """Determine if an event should be excluded based on the filter criteria.

        This is the inverse of the include method.

        Args:
            event: The Event object to check against the filter criteria.

        Returns:
            bool: True if the event should be excluded, False if it should be included.

        """
        return not self.include(event)
