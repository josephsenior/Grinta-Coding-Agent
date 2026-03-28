"""Aggregated conversation info response structures for pagination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.gateway.schemas.conversation_info import ConversationInfo

if TYPE_CHECKING:
    pass


@dataclass
class ConversationInfoResultSet:
    """Paginated container of ConversationInfo results returned from routes."""

    results: list[ConversationInfo] = field(default_factory=list)
    next_page_id: str | None = None
