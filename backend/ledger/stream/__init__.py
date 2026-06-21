"""Event stream implementation with pub/sub and persistence helpers.

Backpressure is delegated to :mod:`backend.ledger.stream.backpressure` and durable
persistence / WAL recovery to :mod:`backend.ledger.stream.persistence`.
"""

from __future__ import annotations

from enum import Enum

from backend.ledger.stream.event_stream import (  # noqa: F401
    EventStream,
    _warn_unclosed_stream,
    session_exists,
)
from backend.utils.async_helpers.async_utils import call_sync_from_async  # noqa: F401
from backend.core.workspace_resolution import workspace_agent_state_dir  # noqa: F401


class EventStreamSubscriber(str, Enum):
    """Lightweight wrapper attaching callbacks to event stream broadcast queue."""

    AGENT_CONTROLLER = 'agent_controller'
    CLI = 'cli'
    SERVER = 'server'
    RUNTIME = 'runtime'
    MEMORY = 'memory'
    MAIN = 'main'
    TEST = 'test'


__all__ = [
    'EventStream',
    'EventStreamSubscriber',
    '_warn_unclosed_stream',
    'call_sync_from_async',
    'workspace_agent_state_dir',
    'session_exists',
]
