"""Legacy post-compact helpers — prefer ``context.prompt.compact_snapshot``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.context.prompt.compact_snapshot import (
    COMPACT_SNAPSHOT_MARKER,
    build_compact_snapshot_body,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


def build_post_compact_attachment_text(
    state: State | None,
    events: list[Event],
) -> str:
    """Legacy wrapper — snapshot now lives inside ``<CONTEXT_PACKET>``."""
    body = build_compact_snapshot_body(state, events)
    if not body:
        return ''
    return f'{COMPACT_SNAPSHOT_MARKER}\n{body}\n</COMPACT_SNAPSHOT>'


__all__ = [
    'COMPACT_SNAPSHOT_MARKER',
    'build_compact_snapshot_body',
    'build_post_compact_attachment_text',
]
