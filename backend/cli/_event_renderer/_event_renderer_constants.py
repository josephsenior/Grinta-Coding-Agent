"""Shared constants used by CLIEventRenderer and its mixin files.

Placed in a dedicated module to avoid circular imports between the main
event_renderer.py (which imports the mixins) and the mixins (which need these
constants).
"""
from __future__ import annotations

from backend.core.enums import AgentState
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import NullAction
from backend.ledger.observation import NullObservation

# Events to silently skip (mirrors gateway filtering).
SKIP_ACTIONS: tuple[type, ...] = (NullAction,)
SKIP_OBSERVATIONS: tuple[type, ...] = (NullObservation,)
IDLE_STATES: frozenset[AgentState] = frozenset(
    {
        AgentState.AWAITING_USER_INPUT,
        AgentState.FINISHED,
        AgentState.ERROR,
        AgentState.STOPPED,
        AgentState.REJECTED,
    }
)
# Subscriber ID for the CLI renderer.
SUBSCRIBER: EventStreamSubscriber = EventStreamSubscriber.CLI
