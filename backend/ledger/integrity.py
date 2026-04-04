"""Event store integrity helpers.

App stores each event as an individual JSON file. A crash or partial write can
leave a file unreadable. These helpers provide best-effort iteration that stops
cleanly at the last valid event.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:  # pragma: no cover
    from backend.ledger.event import Event
    from backend.ledger.event_filter import EventFilter
    from backend.ledger.event_store import EventStore


def iter_events_until_corrupt(
    event_store: EventStore,
    *,
    start_id: int = 0,
    event_filter: EventFilter | None = None,
    limit: int | None = None,
) -> Iterable[Event]:
    """Yield events in ascending order, stopping at first corrupt event.

    This protects long sessions from a single unreadable event file by returning
    all events up to the last valid id.
    """
    yielded = 0
    for idx in range(max(0, start_id), event_store.cur_id):
        if limit is not None and yielded >= limit:
            return
        try:
            event = event_store.get_event(idx)
        except FileNotFoundError:
            # Missing file: treat as a gap, stop to preserve ordering guarantees.
            logger.warning('Event file missing at id=%s; stopping replay', idx)
            return
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning('Corrupt event at id=%s; stopping replay: %s', idx, exc)
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning('Unexpected replay error at id=%s; stopping: %s', idx, exc)
            return

        if event_filter is not None and not event_filter.include(event):
            continue

        yield event
        yielded += 1
