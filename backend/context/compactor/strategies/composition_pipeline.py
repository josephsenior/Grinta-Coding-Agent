"""Composition pipeline compactor.

Runs multiple compaction layers in sequence instead of selecting a single
strategy. Each layer handles one dimension of context pressure:

  1. Microcompact — clear old tool result content bodies, keep structure
  2. Snip — hard cap on total event count
  3. Summary — LLM-prose summary of events before recency window
  4. Recent keep — ensure N most recent events stay raw
  5. Post-compact reattach — re-inject file reads for changed files
  6. Reactive — safety-net drop on overflow
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.context.compactor.compactor import Compactor, View
from backend.context.compactor.strategies.layers import (
    LAYERS,
    REACTIVE_COMPACT_RATIO,
    microcompact_layer,
    reactive_compact_layer,
    snip_layer,
    summary_layer,
)

if TYPE_CHECKING:
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.event import Event


class CompositionCompactor(Compactor):
    """Compactor that applies all layers in sequence.

    Each layer transforms the event list independently. Layers are
    composed so that later layers benefit from the work of earlier ones
    (e.g., microcompact reduces bloat before the summary layer runs).
    """

    def __init__(
        self,
        microcompact_recency: int = 50,
        snip_max_events: int = 1000,
        summary_recency: int = 50,
        post_compact_budget: int = 50000,
        post_compact_max_files: int = 5,
        reactive_max_events: int | None = None,
    ) -> None:
        super().__init__()
        self.microcompact_recency = microcompact_recency
        self.snip_max_events = snip_max_events
        self.summary_recency = summary_recency
        self.post_compact_budget = post_compact_budget
        self.post_compact_max_files = post_compact_max_files
        self.reactive_max_events = (
            reactive_max_events
            if reactive_max_events is not None
            else max(1, int(snip_max_events * REACTIVE_COMPACT_RATIO))
        )
        self._summary_compactor: Compactor | None = None

    def set_summary_compactor(self, compactor: Compactor | None) -> None:
        """Set the LLM-based summary compactor for the summary layer.

        When set, the summary layer delegates to this compactor for
        events before the recency window. Events within the recency
        window are kept raw.
        """
        self._summary_compactor = compactor

    async def compact(self, view: View) -> View:
        """Run every composition layer in order on the view's events.

        Each layer receives the output of the previous layer. The final
        transformed event list is returned as a new View.
        """
        events: list[Event] = list(view.events)

        for name, layer_fn in LAYERS:
            if name == 'summary' and self._summary_compactor is not None:
                events = await summary_layer(
                    events,
                    state=None,
                    summary_compactor=self._summary_compactor,
                    summary_recency=self.summary_recency,
                )
            elif name == 'microcompact':
                events = await microcompact_layer(
                    events,
                    state=None,
                    recency_window=self.microcompact_recency,
                )
            elif name == 'snip':
                events = await snip_layer(
                    events,
                    state=None,
                    max_events=self.snip_max_events,
                )
            elif name == 'reactive':
                events = await reactive_compact_layer(
                    events,
                    state=None,
                    max_events=self.reactive_max_events,
                )
            else:
                events = await layer_fn(events, state=None)
            self.add_metadata(f'layer_{name}_count', len(events))

        return View(events=events)

    @classmethod
    def from_config(
        cls,
        config: Any,
        llm_registry: LLMRegistry,
    ) -> CompositionCompactor:
        kwargs = config.model_dump(exclude={'type', 'llm_config'})
        compactor = CompositionCompactor(**kwargs)

        llm_config = getattr(config, 'llm_config', None)
        if llm_config is not None and llm_registry is not None:
            compactor._build_summary_compactor(llm_config, llm_registry)

        return compactor

    def _build_summary_compactor(
        self,
        llm_config: object,
        llm_registry: LLMRegistry,
    ) -> None:
        """Create a StructuredSummaryCompactor for the summary layer."""
        try:
            from backend.context.compactor.compactor import Compactor as CompactorBase
            from backend.core.config.compactor_config import (
                StructuredSummaryCompactorConfig,
            )

            inner_config = StructuredSummaryCompactorConfig(
                llm_config=llm_config,
                max_size=2,
                keep_first=0,
            )
            self._summary_compactor = CompactorBase.from_config(
                inner_config, llm_registry
            )
        except Exception as exc:
            self.add_metadata('summary_compactor_build_error', str(exc))
            self._summary_compactor = None


def _register_config() -> None:
    from backend.core.config.compactor_config import (
        CompositionCompactorConfig,
    )

    CompositionCompactor.register_config(CompositionCompactorConfig)


_register_config()
