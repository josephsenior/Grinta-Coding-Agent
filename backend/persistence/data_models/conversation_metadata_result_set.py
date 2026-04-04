"""Container models for paginated conversation metadata results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.persistence.data_models.conversation_metadata import (
        ConversationMetadata,
    )


@dataclass
class ConversationMetadataResultSet:
    """Paginated metadata listing returned by conversation store search."""

    results: list[ConversationMetadata] = field(default_factory=list)
    next_page_id: str | None = None
