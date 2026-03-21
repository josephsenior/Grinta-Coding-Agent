"""Decision tracking and context anchoring for ConversationMemory.

Extracted from :mod:`backend.memory.conversation_memory` to keep module
sizes within the repository guideline (~400 LOC).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.core.logger import forge_logger as logger
from backend.memory.graph_rag import GraphRAG
from backend.memory.graph_store import GraphMemoryStore
from backend.memory.memory_types import ContextAnchor, Decision, DecisionType
from backend.memory.vector_store import EnhancedVectorStore

# Caps for text injected into the leading system message (token control).
_CONTEXT_SUMMARY_MAX_ANCHORS = 5
_CONTEXT_SUMMARY_MAX_DECISIONS = 5


class ContextTracker:
    """Manages decisions, context anchors, and optional vector memory.

    Used as a mixin / composition helper by
    :class:`~backend.memory.conversation_memory.ConversationMemory`.
    """

    def __init__(
        self,
        *,
        vector_store: EnhancedVectorStore | None = None,
        graph_store: GraphMemoryStore | None = None,
        max_decisions: int = 200,
        max_anchors: int = 200,
    ) -> None:
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.graph_rag: GraphRAG | None = None
        if self.vector_store is not None and self.graph_store is not None:
            self.graph_rag = GraphRAG(self.vector_store, self.graph_store)
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
            ranked = sorted(
                self.anchors.values(), key=lambda x: x.importance, reverse=True
            )[:_CONTEXT_SUMMARY_MAX_ANCHORS]
            for anchor in ranked:
                summary_parts.append(f"- [{anchor.category.upper()}] {anchor.content}")

        if self.decisions:
            summary_parts.append("## Recent Decisions")
            recent = sorted(
                self.decisions.values(), key=lambda x: x.timestamp, reverse=True
            )[:_CONTEXT_SUMMARY_MAX_DECISIONS]
            for d in recent:
                summary_parts.append(f"- {d.description}")

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

            # Optional GraphRAG indexing (best-effort). Only index when we have
            # a stable identifier for a code artifact.
            if self.graph_rag is not None:
                meta = metadata or {}
                file_path = meta.get("file_path")
                if isinstance(file_path, str) and file_path.strip():
                    self.graph_rag.index_code_file(file_path, content)
        except Exception as e:
            logger.warning("Failed to store event in memory: %s", e)

    def recall_from_memory(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant context from persistent vector memory."""
        if not self.vector_store:
            return []
        try:
            results = self.vector_store.search(query, k=k)

            # Prepend GraphRAG context (semantic + structural) when available.
            if self.graph_rag is not None:
                retrieval = self.graph_rag.retrieve(query, max_results=k)
                formatted = self.graph_rag.format_context(retrieval)
                results = [
                    {
                        "role": "graph_rag",
                        "content_text": formatted,
                        "metadata": {
                            "graph_rag": True,
                            "stats": retrieval.get("stats", {}),
                            "seed_nodes": retrieval.get("seed_nodes", []),
                        },
                        "score": 1.0,
                    },
                    *results,
                ]
            logger.debug(
                "Retrieved %d relevant memories for query: %s", len(results), query[:50]
            )
            return results
        except Exception as e:
            logger.warning("Failed to retrieve from memory: %s", e)
            return []
