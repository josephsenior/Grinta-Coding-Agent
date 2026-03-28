"""Async utilities for iterating over event stores."""

from collections.abc import AsyncIterator
from typing import Any

from backend.ledger.event import Event
from backend.ledger.event_store import EventStore


class AsyncEventStoreWrapper:
    """Async wrapper for EventStore to enable async iteration over events.

    Wraps synchronous event store operations to work in async context.
    """

    def __init__(self, event_store: EventStore, *args: Any, **kwargs: Any) -> None:
        """Initialize async wrapper with event store and search parameters.

        Args:
            event_store: Event store to wrap
            *args: Positional arguments for search_events
            **kwargs: Keyword arguments for search_events

        """
        self.event_store = event_store
        self.args = args
        self.kwargs = kwargs

    async def __aiter__(self) -> AsyncIterator[Event]:
        """Iterate over events asynchronously.

        Events are yielded directly. ``search_events`` already runs in this coroutine;
        using the default executor per event was redundant and breaks during shutdown
        when the interpreter shuts down the thread pool while replay is still active.
        """
        for event in self.event_store.search_events(*self.args, **self.kwargs):
            yield event
