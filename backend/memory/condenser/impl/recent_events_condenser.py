"""Condenser that retains only the most recent events while respecting required prefixes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.condenser_config import RecentEventsCondenserConfig
    from backend.llm.llm_registry import LLMRegistry

from backend.memory.condenser.condenser import Condensation, Condenser
from backend.memory.view import View


class RecentEventsCondenser(Condenser):
    """A condenser that only keeps a certain number of the most recent events."""

    def __init__(self, keep_first: int = 1, max_events: int = 10) -> None:
        """Initialize a simple recency-based condenser that keeps prefix and recent events.

        This condenser implements a straightforward windowing strategy: always preserve a fixed
        number of initial events (keep_first), then fill the remaining space with only the most
        recent events from the tail of the event sequence. This is useful as a lightweight fallback
        when full LLM-based summarization is not needed or too expensive.

        Args:
            keep_first: Number of initial events to always preserve without filtering.
                       Typically 1 to preserve initial context or system messages.
            max_events: Maximum total number of events to keep after condensation.
                       Must be >= keep_first or tail will be empty.

        Side Effects:
            - Initializes parent Condenser for metadata management
            - Sets up retention parameters for condense() method

        Notes:
            - Strategy: Combine keep_first prefix with recent tail to reach max_events total
            - If max_events <= keep_first, only prefix is kept (tail_length = 0)
            - No LLM involved: purely mechanical time-based retention
            - Examples: keep_first=1, max_events=10 → keep event 0 + last 9 events
            - Useful for memory constraints or high-frequency condensation scenarios

        Example:
            >>> condenser = RecentEventsCondenser(keep_first=1, max_events=10)
            >>> condenser.max_events
            10
            >>> condenser.keep_first
            1

        """
        self.keep_first = keep_first
        self.max_events = max_events
        super().__init__()

    def condense(self, view: View) -> View | Condensation:
        """Keep only the most recent events (up to `max_events`)."""
        head = view[: self.keep_first]
        tail_length = max(0, self.max_events - len(head))
        tail = view[-tail_length:]
        return View(events=head + tail)

    @classmethod
    def from_config(cls, config: RecentEventsCondenserConfig, llm_registry: LLMRegistry) -> RecentEventsCondenser:
        """Create condenser using values from configuration object."""
        from backend.core.pydantic_compat import model_dump_with_options

        return RecentEventsCondenser(**model_dump_with_options(config, exclude={"type"}))


# Lazy registration to avoid circular imports
def _register_config():
    """Register RecentEventsCondenserConfig with the RecentEventsCondenser factory.

    Defers import of RecentEventsCondenserConfig to avoid circular dependency between
    condenser implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate condensers from config objects.

    Side Effects:
        - Imports RecentEventsCondenserConfig from backend.core.config.condenser_config
        - Registers config class with RecentEventsCondenser.register_config() factory

    Notes:
        - Must be called at module level after RecentEventsCondenser class definition
        - Pattern reused across all condenser implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.condenser_config import RecentEventsCondenserConfig

    RecentEventsCondenser.register_config(RecentEventsCondenserConfig)


_register_config()
