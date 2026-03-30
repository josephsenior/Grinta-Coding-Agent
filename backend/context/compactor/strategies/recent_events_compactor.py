"""Compactor that retains only the most recent events while respecting required prefixes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.config.compactor_config import RecentEventsCompactorConfig
    from backend.inference.llm_registry import LLMRegistry

from backend.context.compactor.compactor import Compaction, Compactor
from backend.context.view import View


class RecentEventsCompactor(Compactor):
    """A compactor that only keeps a certain number of the most recent events."""

    def __init__(self, keep_first: int = 1, max_events: int = 10) -> None:
        """Initialize a simple recency-based compactor that keeps prefix and recent events.

        This compactor implements a straightforward windowing strategy: always preserve a fixed
        number of initial events (keep_first), then fill the remaining space with only the most
        recent events from the tail of the event sequence. This is useful as a lightweight fallback
        when full LLM-based summarization is not needed or too expensive.

        Args:
            keep_first: Number of initial events to always preserve without filtering.
                       Typically 1 to preserve initial context or system messages.
            max_events: Maximum total number of events to keep after condensation.
                       Must be >= keep_first or tail will be empty.

        Side Effects:
            - Initializes the parent Compactor for metadata management
            - Sets up retention parameters for condense() method

        Notes:
            - Strategy: Combine keep_first prefix with recent tail to reach max_events total
            - If max_events <= keep_first, only prefix is kept (tail_length = 0)
            - No LLM involved: purely mechanical time-based retention
            - Examples: keep_first=1, max_events=10 → keep event 0 + last 9 events
            - Useful for memory constraints or high-frequency condensation scenarios

        Example:
            >>> compactor = RecentEventsCompactor(keep_first=1, max_events=10)
            >>> compactor.max_events
            10
            >>> compactor.keep_first
            1

        """
        self.keep_first = keep_first
        self.max_events = max_events
        super().__init__()

    def compact(self, view: View) -> View | Compaction:
        """Keep only the most recent events (up to `max_events`)."""
        head = view[: self.keep_first]
        tail_length = max(0, self.max_events - len(head))
        tail = view[-tail_length:]
        return View(events=head + tail)

    @classmethod
    def from_config(
        cls, config: Any, llm_registry: LLMRegistry
    ) -> RecentEventsCompactor:
        """Create a compactor using values from the configuration object."""
        from backend.core.pydantic_compat import model_dump_with_options

        return RecentEventsCompactor(
            **model_dump_with_options(config, exclude={"type"})
        )


# Lazy registration to avoid circular imports
def _register_config():
    """Register RecentEventsCompactorConfig with the RecentEventsCompactor factory.

    Defers import of RecentEventsCompactorConfig to avoid circular dependency between
    compactor implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate compactors from config objects.

    Side Effects:
        - Imports RecentEventsCompactorConfig from backend.core.config.compactor_config
        - Registers config class with RecentEventsCompactor.register_config() factory

    Notes:
        - Must be called at module level after RecentEventsCompactor class definition
        - Pattern reused across all compactor implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.compactor_config import RecentEventsCompactorConfig

    RecentEventsCompactor.register_config(RecentEventsCompactorConfig)


_register_config()
