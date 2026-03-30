"""Data models for conversation memory state (decisions, anchors)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DecisionType(Enum):
    """Types of decisions tracked."""

    ARCHITECTURAL = "architectural"  # System design choices
    IMPLEMENTATION = "implementation"  # Code implementation decisions
    TECHNICAL = "technical"  # Tech stack, library choices
    FUNCTIONAL = "functional"  # Feature behavior
    CONSTRAINT = "constraint"  # Explicit constraints/requirements
    WORKFLOW = "workflow"  # Process/workflow decisions


class MemoryTier(Enum):
    """Memory tiers for hierarchical storage."""

    SHORT_TERM = "short_term"  # Last few exchanges
    WORKING = "working"  # Active conversation context
    LONG_TERM = "long_term"  # Persistent across sessions


@dataclass
class Decision:
    """A tracked decision made during conversation."""

    decision_id: str
    type: DecisionType
    description: str
    rationale: str
    timestamp: datetime
    context: str  # What was the conversation context?
    alternatives_considered: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0-1
    tier: MemoryTier = MemoryTier.WORKING
    anchor: bool = False  # Should this be anchored (never pruned)?

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "decision_id": self.decision_id,
            "type": self.type.value,
            "description": self.description,
            "rationale": self.rationale,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "alternatives_considered": self.alternatives_considered,
            "confidence": self.confidence,
            "tier": self.tier.value,
            "anchor": self.anchor,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Decision:
        """Create from dictionary."""
        return cls(
            decision_id=data["decision_id"],
            type=DecisionType(data["type"]),
            description=data["description"],
            rationale=data["rationale"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            context=data["context"],
            alternatives_considered=data.get("alternatives_considered", []),
            confidence=data.get("confidence", 1.0),
            tier=MemoryTier(data.get("tier", "working")),
            anchor=data.get("anchor", False),
        )


@dataclass
class ContextAnchor:
    """Critical information that should never be pruned."""

    anchor_id: str
    content: str
    category: str  # "requirement", "constraint", "goal", "architecture"
    importance: float  # 0-1
    timestamp: datetime
    last_accessed: datetime
    access_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "anchor_id": self.anchor_id,
            "content": self.content,
            "category": self.category,
            "importance": self.importance,
            "timestamp": self.timestamp.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextAnchor:
        """Create from dictionary."""
        return cls(
            anchor_id=data["anchor_id"],
            content=data["content"],
            category=data["category"],
            importance=data["importance"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            access_count=data.get("access_count", 0),
        )
