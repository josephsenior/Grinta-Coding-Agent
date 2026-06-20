"""Event stream implementation with pub/sub and persistence helpers.

Backpressure is delegated to :mod:`backend.ledger.stream.backpressure` and durable
persistence / WAL recovery to :mod:`backend.ledger.stream.persistence`.
"""

from __future__ import annotations

from enum import Enum

from backend.ledger.stream.event_stream import EventStream, session_exists  # noqa: F401


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
    'session_exists',
]
