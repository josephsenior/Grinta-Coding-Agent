"""Data models describing stored conversation metadata and triggers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from backend.core.provider_types import ProviderType

if TYPE_CHECKING:
    pass


class ConversationTrigger(str, Enum):
    """Describe external event that initiated a conversation."""

    GUI = "gui"
    SUGGESTED_TASK = "suggested_task"
    PLAYBOOK_MANAGEMENT = "playbook_management"
    EXTERNAL_API = "external_api"
    REMOTE_API_KEY = "remote_api_key"
    UNKNOWN = "unknown"


@dataclass
class ConversationMetadata:
    """Persisted metadata about a conversation for UI/state restoration."""

    conversation_id: str
    title: str
    selected_repository: str | None
    user_id: str | None = None
    selected_branch: str | None = None
    vcs_provider: ProviderType | None = None
    last_updated_at: datetime | None = None
    trigger: ConversationTrigger | None = None
    pr_number: list[int] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    llm_model: str | None = None
    accumulated_cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    name: str | None = None

    def __post_init__(self) -> None:
        """Set default name and last-updated fields based on title and creation time."""
        if self.name is None:
            self.name = self.title
        if self.last_updated_at is None:
            self.last_updated_at = self.created_at
