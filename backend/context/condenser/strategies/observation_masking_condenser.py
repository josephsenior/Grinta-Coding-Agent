"""Condenser that masks content of sensitive or verbose observation events."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.condenser_config import ObservationMaskingCondenserConfig
from backend.ledger.observation import Observation
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.context.condenser.condenser import Condensation, Condenser
from backend.context.view import View

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.inference.llm_registry import LLMRegistry


class ObservationMaskingCondenser(Condenser):
    """A condenser that masks the values of observations outside of a recent attention window."""

    def __init__(self, attention_window: int = 5) -> None:
        """Initialize a condenser that masks old observation values while keeping recent ones visible.

        This condenser implements an attention window strategy that preserves the structure of the
        event sequence while masking (replacing with "<MASKED>") the content of observations that
        fall outside a recent attention window. This reduces token usage while maintaining event
        count for continuity, and is often used before LLM summarization to focus the LLM on
        recent context without forcing it to process old observations.

        Args:
            attention_window: Number of most recent events to keep fully visible.
                             Observations before this window are replaced with "<MASKED>" placeholder.
                             Default 5 keeps the 5 most recent events unmasked.

        Side Effects:
            - Initializes parent Condenser for metadata management
            - Stores attention_window parameter for use in condense() filtering

        Notes:
            - Non-destructive: Events are masked, not removed (keeps event count for indexing)
            - Observation-specific: Only Observation instances are masked, other event types pass through
            - Converted to AgentCondensationObservation: Masked observations become observations of type
              AgentCondensationObservation with content "<MASKED>"
            - Use case: Chained before summarization to reduce LLM prompt size
            - Examples: attention_window=5 → mask observations at positions 0 through (len(view) - 5)

        Example:
            >>> condenser = ObservationMaskingCondenser(attention_window=5)
            >>> condenser.attention_window
            5

        """
        self.attention_window = attention_window
        super().__init__()

    def condense(self, view: View) -> View | Condensation:
        """Replace the content of observations outside of the attention window with a placeholder."""
        results: list[Event] = []
        for i, event in enumerate(view):
            if isinstance(event, Observation) and i < len(view) - self.attention_window:
                results.append(AgentCondensationObservation("<MASKED>"))
            else:
                results.append(event)
        return View(events=results)

    @classmethod
    def from_config(
        cls,
        config: ObservationMaskingCondenserConfig,
        llm_registry: LLMRegistry,
    ) -> ObservationMaskingCondenser:
        """Instantiate condenser from configuration values."""
        from backend.core.pydantic_compat import model_dump_with_options

        return ObservationMaskingCondenser(
            **model_dump_with_options(config, exclude={"type"})
        )


# Lazy registration to avoid circular imports
def _register_config():
    """Register ObservationMaskingCondenserConfig with the ObservationMaskingCondenser factory.

    Defers import of ObservationMaskingCondenserConfig to avoid circular dependency between
    condenser implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate condensers from config objects.

    Side Effects:
        - Imports ObservationMaskingCondenserConfig from backend.core.config.condenser_config
        - Registers config class with ObservationMaskingCondenser.register_config() factory

    Notes:
        - Must be called at module level after ObservationMaskingCondenser class definition
        - Pattern reused across all condenser implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.condenser_config import (
        BrowserOutputCondenserConfig,
        ObservationMaskingCondenserConfig,
    )

    ObservationMaskingCondenser.register_config(ObservationMaskingCondenserConfig)
    ObservationMaskingCondenser.register_config(BrowserOutputCondenserConfig)


_register_config()
