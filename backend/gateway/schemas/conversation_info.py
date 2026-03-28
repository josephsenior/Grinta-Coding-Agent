"""Data models representing high-level conversation metadata and status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.core.provider_types import ProviderType
from backend.core.enums import RuntimeStatus
from backend.persistence.data_models.conversation_metadata import ConversationTrigger
from backend.persistence.data_models.conversation_status import ConversationStatus

if TYPE_CHECKING:
    pass


@dataclass
class ConversationInfo:
    """Information about a conversation. This combines conversation metadata with.

    information on whether a conversation is currently running.
    """

    conversation_id: str
    title: str
    last_updated_at: datetime | None = None
    status: ConversationStatus = ConversationStatus.STOPPED
    runtime_status: RuntimeStatus | None = None
    agent_state: AgentState | None = None
    selected_repository: str | None = None
    selected_branch: str | None = None
    vcs_provider: ProviderType | None = None
    trigger: ConversationTrigger | None = None
    num_connections: int = 0
    url: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pr_number: list[int] = field(default_factory=list)
