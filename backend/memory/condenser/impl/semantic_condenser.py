"""Semantic Condenser - Intelligent Compression with Meaning Preservation.

Uses semantic similarity via SentenceTransformers to compress context
while preserving the most critical information relative to the current task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger
from backend.memory.condenser.condenser import BaseLLMCondenser, Condensation
from backend.memory.view import View

if TYPE_CHECKING:
    from backend.events.event import Event


try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    from numpy.linalg import norm
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


class SemanticCondenser(BaseLLMCondenser):
    """Semantic condenser that intelligently compresses context using embeddings.

    Features:
    - computes embeddings for conversation history
    - semantic similarity scoring against recent context
    - preserves first N events (system/task context)
    - keeps recent window (short-term memory)
    - selectively forgets low-relevance middle events
    - summarizes forgotten chunks
    """

    def __init__(
        self,
        llm: Any = None,
        max_size: int = 100,
        keep_first: int = 1,
        max_event_length: int = 10000,
        similarity_threshold: float = 0.5,
        model_name: str = "all-MiniLM-L6-v2",
        token_budget: int | None = None,
    ) -> None:
        """Initialize semantic condenser.

        Args:
            llm: LLM for summarization
            max_size: Maximum number of events to keep
            keep_first: Number of initial events to always keep
            max_event_length: Max chars per event (unused by embeddings but kept for compat)
            similarity_threshold: Validation threshold (0-1)
            model_name: SentenceTransformer model name
            token_budget: Optional token budget
        """
        super().__init__(llm, max_size, keep_first, max_event_length)
        self.token_budget = token_budget
        
        if not HAS_SENTENCE_TRANSFORMERS:
            logger.warning(
                "sentence-transformers not installed; SemanticCondenser will degrade to FIFO."
            )
            self.model = None
        else:
            try:
                logger.info(f"Loading SentenceTransformer: {model_name}")
                self.model = SentenceTransformer(model_name)
            except Exception as e:
                logger.error(f"Failed to load SentenceTransformer model {model_name}: {e}")
                self.model = None

        self.similarity_threshold = similarity_threshold

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        """Extract semantic-specific config args."""
        args = BaseLLMCondenser._get_extra_config_args(config)
        if hasattr(config, "similarity_threshold"):
            args["similarity_threshold"] = config.similarity_threshold
        if hasattr(config, "model_name"):
            args["model_name"] = config.model_name
        return args

    def get_condensation(self, view: View) -> Condensation:
        """Generate a condensation using semantic relevance."""
        events = view.events
        total_events = len(events)
        
        # Fallback if no model or within limits
        if not self.model or total_events <= self.max_size:
            return self._fifo_condense(events)

        # 1. Define "Query" (Recent Context)
        # We use the last 5-10 events as the "query" to determine what's relevant
        recent_window = max(5, int(self.max_size * 0.1))
        # Ensure we don't request more events than available
        available_recent = min(recent_window, total_events)
        query_events = events[-available_recent:]
        
        # Build query text from content/messages
        query_parts = []
        for e in query_events:
            content = getattr(e, "message", getattr(e, "content", getattr(e, "thought", "")))
            if content:
                query_parts.append(str(content)[:200])
        query_text = "\n".join(query_parts)
        if not query_text.strip():
            query_text = "current task context"

        # 2. Embed Query
        try:
            query_embedding = self.model.encode(query_text)
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return self._fifo_condense(events)

        # 3. Identify Candidate Range (Middle)
        # Keep fixed start and fixed end (recent window)
        candidates_start = self.keep_first
        # We must keep the recent window to maintain coherence
        # The candidates are BETWEEN start and (end - recent_window)
        candidates_end_index = total_events - recent_window
        
        if candidates_end_index <= candidates_start:
             return self._fifo_condense(events)

        candidate_events = events[candidates_start:candidates_end_index]
        
        if not candidate_events:
            return self._fifo_condense(events)

        # Prepare texts for candidates
        candidate_texts = []
        for e in candidate_events:
            txt = getattr(e, "message", getattr(e, "content", getattr(e, "thought", "")))
            candidate_texts.append(str(txt)[:500] if txt else "empty_event")
        
        # 4. Batch Embed Candidates
        try:
            candidate_embeddings = self.model.encode(candidate_texts)
        except Exception as e:
            logger.warning(f"Batch embedding failed: {e}")
            return self._fifo_condense(events)
        
        # 5. Compute Similarities
        scores = []
        q_norm = norm(query_embedding)
        
        for emb in candidate_embeddings:
            s_norm = norm(emb)
            if q_norm == 0 or s_norm == 0:
                scores.append(0.0)
            else:
                scores.append(np.dot(query_embedding, emb) / (q_norm * s_norm))

        # 6. determine how many to remove
        # We want to end up with `max_size` events total.
        # current total = total_events
        # needed = max_size
        num_to_remove = total_events - self.max_size
        
        if num_to_remove <= 0:
            return self._fifo_condense(events)
            
        if num_to_remove > len(candidate_events):
            # This implies we can't solve it just by reducing the candidate set. 
            # We must remove all candidates + potentially some from recent/start? 
            # Or just accept we are slightly over limit if keep_first/recent are high.
            # But normally we respect keep_first and recent_window and chew into candidates.
            num_to_remove = len(candidate_events)

        # Strategy: Find the window of size `num_to_remove` with lowest average relevance.
        window_size = num_to_remove
        
        current_sum = sum(scores[:window_size])
        min_sum = current_sum
        best_window_start = 0
        
        for i in range(1, len(scores) - window_size + 1):
            current_sum = current_sum - scores[i-1] + scores[i+window_size-1]
            if current_sum < min_sum:
                min_sum = current_sum
                best_window_start = i
        
        # Range in candidate_events to remove
        remove_start_rel = best_window_start
        remove_end_rel = best_window_start + window_size
        
        # Map to absolute indices in `events`
        abs_remove_start = candidates_start + remove_start_rel
        abs_remove_end = candidates_start + remove_end_rel # exclusive
        
        forgotten_events = events[abs_remove_start:abs_remove_end]
        
        avg_score = min_sum / window_size if window_size > 0 else 0
        logger.info(
            f"Semantic Condenser: Removing {len(forgotten_events)} events "
            f"(idx {abs_remove_start}-{abs_remove_end}) with avg score {avg_score:.3f}"
        )

        return self._create_summary_and_result(forgotten_events, avg_score)

    def _create_summary_and_result(self, forgotten_events: list[Event], avg_score: float = 0.0) -> Condensation:
        summary_text = f"Condensed {len(forgotten_events)} events with low semantic relevance (avg={avg_score:.2f})."
        
        # If LLM is available, we could summarize theoretically, but synchronous call here is tricky
        # if LLM requires async. BaseLLMCondenser assumes synchronous get_condensation.
        # So we stick to a metadata summary.
        
        return self._create_condensation_result(forgotten_events, summary_text)

    def _fifo_condense(self, events: list[Event]) -> Condensation:
        """Fallback to FIFO behavior."""
        logger.info("Using FIFO fallback condensation strategy")
        num_to_remove = len(events) - self.max_size
        if num_to_remove <= 0: # Should not happen based on caller logic
             return Condensation(action=None) # type: ignore - needs non-None action usually
             
        start = self.keep_first
        end = start + num_to_remove
        forgotten = events[start:end]
        return self._create_condensation_result(forgotten, f"Condensed {len(forgotten)} events (FIFO).")
