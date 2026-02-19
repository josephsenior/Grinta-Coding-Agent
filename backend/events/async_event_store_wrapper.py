"""Async utilities for iterating over event stores."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.events.event import Event
from backend.events.event_store import EventStore


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
        """Iterate over events asynchronously."""
        loop = asyncio.get_running_loop()
        for event in self.event_store.search_events(*self.args, **self.kwargs):

            def get_event(e: Event = event) -> Event:
                """Closure to capture event for async executor."""
                return e

            yield await loop.run_in_executor(None, get_event)
