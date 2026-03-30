"""Composite compactor that chains multiple strategies sequentially."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.orchestration.state.state import State
    from backend.core.config.compactor_config import CompactorPipelineConfig
    from backend.context.view import View
    from backend.inference.llm_registry import LLMRegistry

from backend.context.compactor.compactor import Compaction, Compactor


class CompactorPipeline(Compactor):
    """Combines multiple compactors into a single compactor.

    This is useful for creating a pipeline of compactors that can be chained together to achieve very specific condensation aims. Each compactor is run in sequence, passing the output view of one to the next, until we reach the end or a `CondensationAction` is returned instead.
    """

    def __init__(self, *compactor: Compactor) -> None:
        """Initialize a pipeline of compactors that execute sequentially.

        Creates a composite compactor that chains multiple compactor implementations together,
        applying them in sequence. Each compactor processes the output of the previous one,
        enabling complex condensation strategies by combining simpler components (e.g., masking
        followed by summarization). If any compactor returns a Condensation result, the pipeline
        stops and returns that result immediately.

        Args:
            *compactor: Variable number of Compactor instances to chain together.
                       Will be converted to a list and executed in order.

        Side Effects:
            - Initializes parent Compactor to set up metadata management infrastructure
            - Stores compactor list for use in compact() and metadata_batch()

        Notes:
            - Pipeline enables composition of compactors: NoOp -> Masking -> Summarization
                        - Early exit on Compaction: If any compactor returns Compaction instead of View,
              remaining compactors are skipped
            - Metadata collection: metadata_batch() aggregates metadata from all compactors
            - Examples: CompactorPipeline(MaskingCompactor(), SummarizingCompactor())

        Example:
            >>> from backend.context.compactor.strategies import RecentEventsCompactor, LLMSummarizingCompactor
            >>> pipeline = CompactorPipeline(
            ...     RecentEventsCompactor(keep_first=1, max_events=50),
            ...     LLMSummarizingCompactor(llm, max_size=100)
            ... )
            >>> len(pipeline.compactors)
            2

        """
        self.compactors = list(compactor)
        super().__init__()

    @contextmanager
    def metadata_batch(self, state: State):
        """Context manager to buffer metadata and flush after all compactors run."""
        try:
            yield
        finally:
            for compactor in self.compactors:
                compactor.write_metadata(state)

    def compact(self, view: View) -> View | Compaction:
        """Sequentially run compactors until one returns a compaction."""
        result: View | Compaction = view
        for compactor in self.compactors:
            if isinstance(result, Compaction):
                break
            result = compactor.compact(result)
        return result

    @classmethod
    def from_config(
        cls, config: Any, llm_registry: LLMRegistry
    ) -> CompactorPipeline:
        """Build a pipeline from config-defined compactor specs."""
        compactors = [Compactor.from_config(c, llm_registry) for c in config.compactors]
        return CompactorPipeline(*compactors)


# Lazy registration to avoid circular imports
def _register_config():
    """Register CompactorPipelineConfig with the CompactorPipeline factory.

    Defers import of CompactorPipelineConfig to avoid circular dependency between
    compactor implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate compactors from config objects.

    Side Effects:
        - Imports CompactorPipelineConfig from backend.core.config.compactor_config
        - Registers config class with CompactorPipeline.register_config() factory

    Notes:
        - Must be called at module level after CompactorPipeline class definition
        - Pattern reused across all compactor implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.compactor_config import CompactorPipelineConfig

    CompactorPipeline.register_config(CompactorPipelineConfig)


_register_config()
