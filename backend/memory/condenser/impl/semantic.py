"""Semantic condenser implementation using SentenceTransformers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger
from backend.memory.condenser.condenser import BaseLLMCondenser, Condensation
from backend.memory.view import View

if TYPE_CHECKING:
    from backend.events.event import Event

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


class SemanticCondenser(BaseLLMCondenser):
    """Condenser that uses semantic similarity to maximize value density.

    Instead of purely FIFO truncation, this condenser:
    1. Computes embeddings for all events in the history.
    2. Keeps the most recent N events (short-term memory).
    3. Keeps events semantically similar to the recent context (long-term relevance).
    4. Summarizes the rest into a coherent narrative.
    """

    def __init__(
        self,
        llm: Any = None,
        max_size: int = 100,
        keep_first: int = 1,
        max_event_length: int = 10000,
        similarity_threshold: float = 0.5,
        model_name: str = "all-MiniLM-L6-v2",
    ) -> None:
        super().__init__(llm, max_size, keep_first, max_event_length)
        if not HAS_SENTENCE_TRANSFORMERS:
            logger.warning(
                "sentence-transformers not installed; SemanticCondenser will degrade to FIFO."
            )
            self.model = None
        else:
            try:
                self.model = SentenceTransformer(model_name)
            except Exception as e:
                logger.error(f"Failed to load SentenceTransformer model {model_name}: {e}")
                self.model = None

        self.similarity_threshold = similarity_threshold

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        """Extract semantic-specific config args."""
        args = super()._get_extra_config_args(config)
        if hasattr(config, "similarity_threshold"):
            args["similarity_threshold"] = config.similarity_threshold
        if hasattr(config, "model_name"):
            args["model_name"] = config.model_name
        return args

    def get_condensation(self, view: View) -> Condensation:
        """Generate a condensation using semantic relevance.

        Algorithm:
        1. Identify "Query" — the recent context (last 10 events).
        2. Embed Query and candidate events (middle range) using SentenceTransformer.
        3. Compute cosine similarity between query and each candidate.
        4. Find the contiguous window of lowest-scoring events to forget (sliding window).
        5. Create condensation result with the forgotten slice and a summary string.

        Falls back to FIFO condensation if semantic model is unavailable or events
        fit within max_size.
        """
        events = view.events
        if not self.model or len(events) <= self.max_size:
            return self._fifo_condense(events)

        recent_window = 10
        candidates_start = self.keep_first
        candidates_end = max(candidates_start, len(events) - recent_window)
        if candidates_end <= candidates_start:
            return self._fifo_condense(events)

        num_to_remove = len(events) - self.max_size
        if num_to_remove <= 0:
            return self._fifo_condense(events)

        scores = self._compute_similarity_scores(events, recent_window, candidates_start, candidates_end)
        best_window_start = self._find_lowest_score_window(scores, num_to_remove)

        abs_start = candidates_start + best_window_start
        forgotten_slice = events[abs_start : abs_start + num_to_remove]
        summary = self._make_summary(forgotten_slice)

        return self._create_condensation_result(forgotten_slice, summary)

    def _compute_similarity_scores(
        self, events: list[Event], recent_window: int, start: int, end: int
    ) -> list[float]:
        """Compute cosine similarity scores between query (recent) and candidate events.

        Uses the last `recent_window` events as the query context. Candidates are
        events in the middle range [start, end). Returns a list of similarity scores
        (0.0–1.0) for each candidate event, where higher means more relevant to
        recent context.
        """
        import numpy as np
        from numpy.linalg import norm

        if self.model is None:
            return [0.0] * (end - start)

        query_events = events[-min(recent_window, len(events)):]
        query_text = "\n".join(
            str(getattr(e, "message", "")) for e in query_events if hasattr(e, "message")
        )
        if not query_text.strip():
            query_text = "current task context"

        query_embedding = self.model.encode(query_text)
        candidate_events = events[start:end]
        candidate_texts = [
            str(getattr(e, "message", getattr(e, "content", "")))[:500]
            for e in candidate_events
        ]
        candidate_embeddings = self.model.encode(candidate_texts)

        q_norm = norm(query_embedding)
        scores = []
        for emb in candidate_embeddings:
            s_norm = norm(emb)
            if q_norm == 0 or s_norm == 0:
                scores.append(0.0)
            else:
                scores.append(float(np.dot(query_embedding, emb) / (q_norm * s_norm)))
        return scores

    def _find_lowest_score_window(self, scores: list[float], window_size: int) -> int:
        """Find start index of sliding window with lowest total score.

        Used to identify the densest cluster of low-relevance events to forget,
        keeping condensation compatible with View's single-summary assumption.
        """
        if window_size <= 0 or len(scores) < window_size:
            return 0
        current_sum = sum(scores[:window_size])
        min_sum = current_sum
        best_start = 0
        for i in range(1, len(scores) - window_size + 1):
            current_sum = current_sum - scores[i - 1] + scores[i + window_size - 1]
            if current_sum < min_sum:
                min_sum = current_sum
                best_start = i
        return best_start

    def _make_summary(self, forgotten_slice: list[Event]) -> str:
        """Generate a summary string for forgotten events.

        Returns a placeholder summary. BaseLLMCondenser does not expose a clean
        sync summarization API here, so we use a compact description.
        """
        return f"Summary of {len(forgotten_slice)} intermediate events."

    def _fifo_condense(self, events: list[Event]) -> Condensation:
        """Fallback to FIFO behavior if semantic fails."""
        # Remove oldest events after keep_first
        # This mirrors standard RollingCondenser logic
        num_to_remove = len(events) - self.max_size
        start = self.keep_first
        end = start + num_to_remove
        forgotten = events[start:end]
        return self._create_condensation_result(forgotten, f"Condensed {len(forgotten)} events.")
