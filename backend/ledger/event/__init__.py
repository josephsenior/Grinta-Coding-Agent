"""Event, event store, filter, and event-stream utilities.

Modules:

- :mod:`backend.ledger.event._event` — ``Event`` dataclass (with the
  re-exported ``EventSource`` enum from :mod:`backend.core.schemas`).
- :mod:`backend.ledger.event.event_filter` — ``EventFilter`` predicate
  used to slice event streams by source / type / turn.
- :mod:`backend.ledger.event.event_store_abc` — ``EventStoreABC`` abstract
  base class for the on-disk / in-memory event stores.
- :mod:`backend.ledger.event.event_store` — concrete ``EventStore`` and
  the page-cache primitives.
- :mod:`backend.ledger.event.event_utils` — pairing utilities that walk
  an event stream to extract ``(Action, Observation)`` tuples.

Public API re-exports — most call sites should be able to keep using
``from backend.ledger.event import Event, EventSource`` (the package
re-exports those) and only opt in to the more specific modules when
needed.
"""

from __future__ import annotations

from backend.ledger.event._event import Event, EventSource

__all__ = ['Event', 'EventSource']
