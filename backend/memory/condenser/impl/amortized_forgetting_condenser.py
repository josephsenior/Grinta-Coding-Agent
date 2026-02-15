"""Condenser that periodically forgets older events once the window exceeds a threshold."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.condenser_config import AmortizedForgettingCondenserConfig
from backend.events.action.agent import CondensationAction
from backend.memory.condenser.condenser import Condensation, RollingCondenser
from backend.memory.view import View

if TYPE_CHECKING:
    from backend.llm.llm_registry import LLMRegistry


class AmortizedForgettingCondenser(RollingCondenser):
    """A condenser that maintains a condensed history and forgets old events when it grows too large."""

    def __init__(self, max_size: int = 100, keep_first: int = 0) -> None:
        """Initialize the condenser.

        Args:
            max_size: Maximum size of history before forgetting.
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

    def condense(self, view: View) -> View | Condensation:
        """Compact, then condense if thresholds are exceeded."""
        if self.should_condense(view):
            return self.get_condensation(view)
        return view

    def get_condensation(self, view: View) -> Condensation:
        """Generate condensation by keeping head and tail events.

        Args:
            view: Memory view to condense

        Returns:
            Condensation with events to forget

        """
        target_size = self.max_size // 2
        head = view[: self.keep_first]
        events_from_tail = target_size - len(head)
        tail = view[-events_from_tail:]
        event_ids_to_keep = {event.id for event in head + tail}
        event_ids_to_forget = {event.id for event in view} - event_ids_to_keep
        event = CondensationAction(
            forgotten_events_start_id=min(event_ids_to_forget),
            forgotten_events_end_id=max(event_ids_to_forget),
        )
        return Condensation(action=event)

    def should_condense(self, view: View) -> bool:
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
        config: AmortizedForgettingCondenserConfig,
        llm_registry: LLMRegistry,
    ) -> AmortizedForgettingCondenser:
        """Create condenser from configuration.

        Args:
            config: Condenser configuration
            llm_registry: LLM registry (not used)

        Returns:
            Configured condenser instance

        """
        from backend.core.pydantic_compat import model_dump_with_options

        kwargs = model_dump_with_options(config, exclude={"type", "token_budget"})
        condenser = AmortizedForgettingCondenser(**kwargs)
        condenser.token_budget = getattr(config, "token_budget", None)
        return condenser


# Lazy registration to avoid circular imports
def _register_config():
    """Register AmortizedForgettingCondenser config class for factory pattern.

    Args:
        None

    Returns:
        None

    Side Effects:
        - Registers AmortizedForgettingCondenserConfig with condenser factory
        - Called at module load time to enable dynamic config creation

    Notes:
        - Deferred import avoids circular dependency on config module
        - Enables from_config class method to work
        - Part of factory pattern for condenser instantiation

    """
    from backend.core.config.condenser_config import AmortizedForgettingCondenserConfig

    AmortizedForgettingCondenser.register_config(AmortizedForgettingCondenserConfig)


_register_config()
