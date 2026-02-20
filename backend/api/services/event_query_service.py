"""Services for querying events safely.

These helpers centralize event-store iteration patterns and normalize failures
so API routes don't need to duplicate defensive handling.
"""

from __future__ import annotations

import itertools

from backend.core.errors import ReplayError
from backend.events.event_store import EventStore


def get_contextual_events_text(
    *,
    event_store: EventStore,
    event_id: int,
    event_filter,
    context_size: int = 4,
) -> str:
    """Return a stringified window of events around an event id.

    - Includes `context_size` events before `event_id` (exclusive) in chronological order
    - Includes `context_size + 1` events starting at `event_id` (inclusive)

    Raises:
        ReplayError: if event iteration fails unexpectedly.
    """
    if event_id < 0:
        raise ReplayError("event_id must be non-negative")
    if context_size < 0:
        raise ReplayError("context_size must be non-negative")

    try:
        context_before = event_store.search_events(
            start_id=max(0, event_id - context_size),
            end_id=event_id - 1,
            filter=event_filter,
            reverse=True,
            limit=context_size,
        )
        context_after = event_store.search_events(
            start_id=event_id,
            filter=event_filter,
            limit=context_size + 1,
        )

        ordered_context_before = list(context_before)
        ordered_context_before.reverse()
        all_events = itertools.chain(ordered_context_before, context_after)
        return "\n".join(str(event) for event in all_events)
    except ReplayError:
        raise
    except Exception as exc:
        raise ReplayError(f"Failed to read contextual events: {exc}") from exc
