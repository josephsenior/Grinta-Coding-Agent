"""Data structures describing running agent loops and their endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.storage.data_models.conversation_status import ConversationStatus

if TYPE_CHECKING:
    from backend.events.event_store_abc import EventStoreABC
    from backend.core.enums import RuntimeStatus


@dataclass
class AgentLoopInfo:
    """Information about an agent loop - the URL on which to locate it and the event store."""

    conversation_id: str
    url: str | None
    event_store: EventStoreABC | None
    status: ConversationStatus = field(default=ConversationStatus.RUNNING)
    runtime_status: RuntimeStatus | None = None
    agent_state: AgentState | None = None
