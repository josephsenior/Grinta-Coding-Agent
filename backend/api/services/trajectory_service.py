"""Trajectory service.

Centralizes trajectory export/replay logic so routes remain thin and semantics
are consistent across HTTP and reconnect flows.
"""

from __future__ import annotations

from typing import Any

from backend.core.errors import ReplayError
from backend.events.event_filter import EventFilter
from backend.events.integrity import iter_events_until_corrupt
from backend.events.serialization import event_to_dict
from backend.api.session.session_contract import ReplayCursor


def export_trajectory(
    *,
    conversation: Any,
    cursor: ReplayCursor,
    exclude_hidden: bool = True,
) -> list[dict[str, Any]]:
    event_filter = EventFilter(exclude_hidden=exclude_hidden)
    trajectory: list[dict[str, Any]] = []

    try:
        for event in iter_events_until_corrupt(
            conversation.event_stream,
            start_id=cursor.start_id,
            event_filter=event_filter,
            limit=cursor.limit,
        ):
            trajectory.append(event_to_dict(event))
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise ReplayError(f"Failed to export trajectory: {exc}") from exc

    return trajectory
