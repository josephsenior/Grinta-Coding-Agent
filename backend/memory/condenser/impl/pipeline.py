"""Composite condenser that chains multiple strategies sequentially."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.core.config.condenser_config import CondenserPipelineConfig
    from backend.memory.view import View
    from backend.llm.llm_registry import LLMRegistry

from backend.memory.condenser.condenser import Condensation, Condenser


class CondenserPipeline(Condenser):
    """Combines multiple condensers into a single condenser.

    This is useful for creating a pipeline of condensers that can be chained together to achieve very specific condensation aims. Each condenser is run in sequence, passing the output view of one to the next, until we reach the end or a `CondensationAction` is returned instead.
    """

    def __init__(self, *condenser: Condenser) -> None:
        """Initialize a pipeline of condensers that execute sequentially.

        Creates a composite condenser that chains multiple condenser implementations together,
        applying them in sequence. Each condenser processes the output of the previous one,
        enabling complex condensation strategies by combining simpler components (e.g., masking
        followed by summarization). If any condenser returns a Condensation result, the pipeline
        stops and returns that result immediately.

        Args:
            *condenser: Variable number of Condenser instances to chain together.
                       Will be converted to a list and executed in order.

        Side Effects:
            - Initializes parent Condenser to set up metadata management infrastructure
            - Stores condenser list for use in condense() and metadata_batch()

        Notes:
            - Pipeline enables composition of condensers: NoOp -> Masking -> Summarization
            - Early exit on Condensation: If any condenser returns Condensation instead of View,
              remaining condensers are skipped
            - Metadata collection: metadata_batch() aggregates metadata from all condensers
            - Examples: CondenserPipeline(MaskingCondenser(), SummarizingCondenser())

        Example:
            >>> from backend.memory.condenser.impl import RecentEventsCondenser, LLMSummarizingCondenser
            >>> pipeline = CondenserPipeline(
            ...     RecentEventsCondenser(keep_first=1, max_events=50),
            ...     LLMSummarizingCondenser(llm, max_size=100)
            ... )
            >>> len(pipeline.condensers)
            2

        """
        self.condensers = list(condenser)
        super().__init__()

    @contextmanager
    def metadata_batch(self, state: State):
        """Context manager to buffer metadata and flush after all condensers run."""
        try:
            yield
        finally:
            for condenser in self.condensers:
                condenser.write_metadata(state)

    def condense(self, view: View) -> View | Condensation:
        """Sequentially run condensers until one returns a condensation."""
        result: View | Condensation = view
        for condenser in self.condensers:
            result = condenser.condense(result)
            if isinstance(result, Condensation):
                break
        return result

    @classmethod
    def from_config(cls, config: CondenserPipelineConfig, llm_registry: LLMRegistry) -> CondenserPipeline:
        """Build a pipeline from config-defined condenser specs."""
        condensers = [Condenser.from_config(c, llm_registry) for c in config.condensers]
        return CondenserPipeline(*condensers)


# Lazy registration to avoid circular imports
def _register_config():
    """Register CondenserPipelineConfig with the CondenserPipeline factory.

    Defers import of CondenserPipelineConfig to avoid circular dependency between
    condenser implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate condensers from config objects.

    Side Effects:
        - Imports CondenserPipelineConfig from backend.core.config.condenser_config
        - Registers config class with CondenserPipeline.register_config() factory

    Notes:
        - Must be called at module level after CondenserPipeline class definition
        - Pattern reused across all condenser implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.condenser_config import CondenserPipelineConfig

    CondenserPipeline.register_config(CondenserPipelineConfig)


_register_config()
