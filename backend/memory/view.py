"""Utility container representing the condensed event view used for prompts."""

from __future__ import annotations

from typing import overload

from pydantic import BaseModel

from backend.core.logger import forge_logger as logger
from backend.events.action.agent import CondensationAction, CondensationRequestAction
from backend.events.event import Event
from backend.events.observation.agent import AgentCondensationObservation


class View(BaseModel):
    """Linearly ordered view of events.

    Produced by a condenser to indicate the included events are ready to process as LLM input.
    """

    events: list[Event]
    unhandled_condensation_request: bool = False

    def __len__(self) -> int:
        """Return the number of events in this view.

        Returns:
            int: Length of events list

        Side Effects:
            None - Pure function

        Notes:
            - Enables len(view) syntax
            - Used for bounds checking in indexing operations

        """
        return len(self.events)

    def __iter__(self):
        """Iterate over events in this view in order.

        Returns:
            Iterator: Event iterator

        Side Effects:
            None - Pure function

        Notes:
            - Enables for event in view: syntax
            - Delegates to events list iterator
            - Preserves event order from condenser

        """
        return iter(self.events)

    @overload
    def __getitem__(self, key: slice) -> list[Event]: ...

    @overload
    def __getitem__(self, key: int) -> Event: ...

    def __getitem__(self, key: object) -> Event | list[Event]:
        """Access events by integer index or slice.

        Args:
            key: Integer index or slice object

        Returns:
            Event if key is int, list[Event] if key is slice

        Side Effects:
            None - Pure function

        Raises:
            IndexError: If int index out of bounds
            ValueError: If key type is neither int nor slice

        Notes:
            - Supports both view[0] and view[1:5] syntax
            - Slice indices properly bounded to view length
            - Delegates to events list for bounds checking

        Example:
            >>> view = View(events=[event1, event2, event3])
            >>> view[0]
            event1
            >>> view[1:]
            [event2, event3]

        """
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self.events))
            return self.events[start:stop:step]
        if isinstance(key, int):
            return self.events[key]
        msg = f"Invalid key type: {type(key)}"
        raise TypeError(msg)

    @staticmethod
    def _collect_forgotten_event_ids(events: list[Event]) -> set[int]:
        """Collect IDs of events that should be forgotten."""
        forgotten_event_ids: set[int] = set()
        for event in events:
            if isinstance(event, CondensationAction):
                forgotten_event_ids.update(event.forgotten)
                forgotten_event_ids.add(event.id)
            if isinstance(event, CondensationRequestAction):
                forgotten_event_ids.add(event.id)
        return forgotten_event_ids

    @staticmethod
    def _find_summary_info(events: list[Event]) -> tuple[str | None, int | None]:
        """Find summary and its offset from condensation actions."""
        return next(
            (
                (event.summary, event.summary_offset)
                for event in reversed(events)
                if isinstance(event, CondensationAction)
                and (event.summary is not None and event.summary_offset is not None)
            ),
            (None, None),
        )

    @staticmethod
    def _check_unhandled_condensation_request(events: list[Event]) -> bool:
        """Check if there's an unhandled condensation request."""
        for event in reversed(events):
            if isinstance(event, CondensationAction):
                return False
            if isinstance(event, CondensationRequestAction):
                return True
        return False

    @staticmethod
    def from_events(events: list[Event]) -> View:
        """Create a view from a list of events, respecting the semantics of any condensation events."""
        # Collect forgotten events
        forgotten_event_ids = View._collect_forgotten_event_ids(events)
        kept_events = [event for event in events if event.id not in forgotten_event_ids]

        # Find and insert summary if available
        summary, summary_offset = View._find_summary_info(events)
        if summary is not None and summary_offset is not None:
            logger.info("Inserting summary at offset %s", summary_offset)
            kept_events.insert(
                summary_offset, AgentCondensationObservation(content=summary)
            )

        # Check for unhandled condensation requests
        unhandled_condensation_request = View._check_unhandled_condensation_request(
            events
        )

        return View(
            events=kept_events,
            unhandled_condensation_request=unhandled_condensation_request,
        )
