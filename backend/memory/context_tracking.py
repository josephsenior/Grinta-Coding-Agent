"""Decision tracking and context anchoring for ConversationMemory.

Extracted from :mod:`backend.memory.conversation_memory` to keep module
sizes within the repository guideline (~400 LOC).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.core.logger import FORGE_logger as logger
from backend.memory.memory_types import ContextAnchor, Decision, DecisionType
from backend.memory.vector_store import EnhancedVectorStore


class ContextTracker:
    """Manages decisions, context anchors, and optional vector memory.

    Used as a mixin / composition helper by
    :class:`~backend.memory.conversation_memory.ConversationMemory`.
    """

    def __init__(
        self,
        *,
        vector_store: EnhancedVectorStore | None = None,
        max_decisions: int = 200,
        max_anchors: int = 200,
    ) -> None:
        self.vector_store = vector_store
        self.decisions: dict[str, Decision] = {}
        self.anchors: dict[str, ContextAnchor] = {}
        self.max_decisions = max_decisions
        self.max_anchors = max_anchors

    def track_decision(
        self,
        description: str,
        rationale: str,
        decision_type: DecisionType,
        context: str,
        confidence: float = 1.0,
    ) -> Decision:
        """Track a decision made during conversation."""
        decision_id = f"decision_{len(self.decisions) + 1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        decision = Decision(
            decision_id=decision_id,
            type=decision_type,
            description=description,
            rationale=rationale,
            timestamp=datetime.now(),
            context=context,
            confidence=confidence,
        )
        self.decisions[decision_id] = decision
        self._prune_decisions_if_needed()
        logger.info("✓ Tracked decision: %s...", description[:50])
        return decision

    def add_anchor(
        self, content: str, category: str, importance: float = 0.9
    ) -> ContextAnchor:
        """Create a context anchor for critical information."""
        anchor_id = (
            f"anchor_{len(self.anchors) + 1}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        anchor = ContextAnchor(
            anchor_id=anchor_id,
            content=content,
            category=category,
            importance=importance,
            timestamp=datetime.now(),
            last_accessed=datetime.now(),
        )
        self.anchors[anchor_id] = anchor
        self._prune_anchors_if_needed()
        logger.info("📌 Anchored %s: %s...", category, content[:50])
        return anchor

    def _prune_decisions_if_needed(self) -> None:
        while len(self.decisions) > self.max_decisions:
            oldest_key = next(iter(self.decisions), None)
            if oldest_key is None:
                break
            self.decisions.pop(oldest_key, None)

    def _prune_anchors_if_needed(self) -> None:
        while len(self.anchors) > self.max_anchors:
            oldest_key = next(iter(self.anchors), None)
            if oldest_key is None:
                break
            self.anchors.pop(oldest_key, None)

    def get_context_summary(self) -> str:
        """Get a summary of active anchors and recent decisions for the prompt."""
        if not self.anchors and not self.decisions:
            return ""

        summary_parts: list[str] = []

        if self.anchors:
            summary_parts.append("## Critical Context (Anchors)")
            for anchor in sorted(
                self.anchors.values(), key=lambda x: x.importance, reverse=True
            ):
                summary_parts.append(f"- [{anchor.category.upper()}] {anchor.content}")

        if self.decisions:
            summary_parts.append("## Recent Decisions")
            recent = sorted(
                self.decisions.values(), key=lambda x: x.timestamp, reverse=True
            )[:5]
            for d in recent:
                summary_parts.append(f"- {d.description} (Rationale: {d.rationale})")

        return "\n".join(summary_parts)

    # ── Vector memory convenience methods ─────────────────────────

    def store_in_memory(
        self,
        event_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store an event in persistent vector memory."""
        if not self.vector_store:
            return
        try:
            self.vector_store.add(
                step_id=event_id,
                role=role,
                artifact_hash=None,
                rationale=None,
                content_text=content,
                metadata=metadata or {},
            )
            logger.debug("Stored event %s in vector memory", event_id)
        except Exception as e:
            logger.warning("Failed to store event in memory: %s", e)

    def recall_from_memory(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant context from persistent vector memory."""
        if not self.vector_store:
            return []
        try:
            results = self.vector_store.search(query, k=k)
            logger.debug(
                "Retrieved %d relevant memories for query: %s", len(results), query[:50]
            )
            return results
        except Exception as e:
            logger.warning("Failed to retrieve from memory: %s", e)
            return []
