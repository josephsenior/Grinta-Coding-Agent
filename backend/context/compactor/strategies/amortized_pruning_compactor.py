"""Compactor that periodically prunes older events once the window exceeds a threshold."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.context.compactor.compactor import Compaction, RollingCompactor
from backend.context.view import View
from backend.ledger.action.agent import CondensationAction

if TYPE_CHECKING:
    from backend.core.config.compactor_config import AmortizedPruningCompactorConfig
    from backend.inference.llm_registry import LLMRegistry


class AmortizedPruningCompactor(RollingCompactor):
    """A compactor that maintains a compacted history and prunes old events when it grows too large."""

    def __init__(self, max_size: int = 100, keep_first: int = 0) -> None:
        """Initialize the compactor.

        Args:
            max_size: Maximum size of history before pruning.
            keep_first: Number of initial events to always keep.

        Raises:
            ValueError: If keep_first is greater than max_size, keep_first is negative, or max_size is non-positive.

        """
        if keep_first >= max_size // 2:
            msg = f"keep_first ({keep_first}) must be less than half of max_size ({max_size})"
            raise ValueError(msg)
        if keep_first < 0:
            msg = f"keep_first ({keep_first}) cannot be negative"
            raise ValueError(msg)
        if max_size < 1:
            msg = f"max_size ({keep_first}) cannot be non-positive"
            raise ValueError(msg)
        self.max_size = max_size
        self.keep_first = keep_first
        super().__init__()

    def compact(self, view: View) -> View | Compaction:
        """Compact, then condense if thresholds are exceeded."""
        if self.should_compact(view):
            return self.get_compaction(view)
        return view

    def get_compaction(self, view: View) -> Compaction:
        """Generate condensation by keeping head and tail events.

        Args:
            view: Memory view to condense

        Returns:
            Compaction with events to prune

        """
        target_size = self.max_size // 2
        head = view[: self.keep_first]
        events_from_tail = target_size - len(head)
        tail = view[-events_from_tail:]
        event_ids_to_keep = {event.id for event in head + tail}
        event_ids_to_prune = {event.id for event in view} - event_ids_to_keep
        event = CondensationAction(
            pruned_events_start_id=min(event_ids_to_prune),
            pruned_events_end_id=max(event_ids_to_prune),
        )
        return Compaction(action=event)

    def should_compact(self, view: View) -> bool:
        """Check if view exceeds max_size threshold.

        Args:
            view: Memory view to check

        Returns:
            True if condensation needed

        """
        return len(view) > self.max_size

    @classmethod
    def from_config(
        cls,
        config: Any,
        llm_registry: LLMRegistry,
    ) -> AmortizedPruningCompactor:
        """Create a compactor from configuration.

        Args:
            config: Compactor configuration
            llm_registry: LLM registry (not used)

        Returns:
            Configured compactor instance

        """
        from backend.core.pydantic_compat import model_dump_with_options

        kwargs = model_dump_with_options(config, exclude={"type", "token_budget"})
        compactor = AmortizedPruningCompactor(**kwargs)
        compactor.token_budget = getattr(config, "token_budget", None)
        return compactor


def _register_config() -> None:
    """Register AmortizedPruningCompactorConfig for the factory pattern."""
    from backend.core.config.compactor_config import AmortizedPruningCompactorConfig

    AmortizedPruningCompactor.register_config(AmortizedPruningCompactorConfig)


_register_config()