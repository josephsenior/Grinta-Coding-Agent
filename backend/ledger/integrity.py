"""Event store integrity helpers.

Grinta stores each event as an individual JSON file. A crash or partial write can
leave a file unreadable. These helpers provide best-effort iteration that stops
cleanly at the last valid event.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:  # pragma: no cover
    from backend.ledger.event import Event
    from backend.ledger.event_filter import EventFilter
    from backend.ledger.event_store import EventStore

_CHECKSUM_KEY = '_grinta_checksum'
_CHECKSUM_ALGORITHM = 'sha256'


def compute_event_checksum(payload: dict) -> str:
    """Compute a SHA-256 hex digest of *payload* excluding any existing checksum."""
    clean = {k: v for k, v in payload.items() if k != _CHECKSUM_KEY}
    canonical = json.dumps(clean, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def embed_checksum(payload: dict) -> dict:
    """Return a new payload with an integrity checksum embedded."""
    result = dict(payload)
    result[_CHECKSUM_KEY] = compute_event_checksum(result)
    return result


def _event_file_has_checksum(payload: dict) -> bool:
    """True when *payload* has a checksum field (i.e. was persisted since checksums were added)."""
    return isinstance(payload.get(_CHECKSUM_KEY), str)


def verify_event_integrity(payload: dict, event_id: int) -> bool:
    """Verify the integrity checksum of a loaded event payload.

    Events persisted before checksum support (missing ``_grinta_checksum``)
    pass through without failure — we do not reject pre-existing events.

    Returns ``False`` only when the checksum is present but mismatched
    (indicating corruption).  Callers should stop iteration or quarantine.
    """
    stored = payload.get(_CHECKSUM_KEY)
    if not isinstance(stored, str):
        return True  # legacy event, no checksum to verify
    computed = compute_event_checksum(payload)
    if computed == stored:
        return True
    logger.warning(
        'Checksum mismatch at event id=%d: stored=%s... computed=%s...',
        event_id,
        stored[:16],
        computed[:16],
    )
    return False


def iter_events_until_corrupt(
    event_store: EventStore,
    *,
    start_id: int = 0,
    event_filter: EventFilter | None = None,
    limit: int | None = None,
) -> Iterable[Event]:
    """Yield events in ascending order, stopping at first corrupt event.

    This protects long sessions from a single unreadable event file by returning
    all events up to the last valid id.  With checksum support, events whose
    stored checksum does not match their content are also treated as corrupt.
    """
    yielded = 0
    for idx in range(max(0, start_id), event_store.cur_id):
        if limit is not None and yielded >= limit:
            return
        try:
            event = event_store.get_event(idx)
        except FileNotFoundError:
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
