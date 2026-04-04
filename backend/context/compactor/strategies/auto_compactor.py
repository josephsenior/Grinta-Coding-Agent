"""Compactor that automatically selects the best strategy for the current session."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.inference.llm_registry import LLMRegistry

from backend.context.compactor.compactor import Compaction, Compactor
from backend.context.compactor.strategies.auto_selector import select_compactor_config
from backend.context.view import View

logger = logging.getLogger(__name__)


class AutoCompactor(Compactor):
    """Analyses the event stream and delegates to the most appropriate compactor.

    On each ``condense()`` call the auto-selector inspects the current events
    and picks a strategy (noop, observation_masking, structured_summary, etc.).
    A delegate compactor is then instantiated from the selected config and the
    actual condensation is forwarded to it.
    """

    def __init__(
        self,
        llm_config: object | None,
        llm_registry: LLMRegistry,
    ) -> None:
        super().__init__()
        # NOTE: This is intentionally *not* just a model string.
        # It can be either:
        # - an LLMConfig instance (preferred; inherits the primary model + keys)
        # - a named LLM config section (e.g. "llm")
        self._llm_config = llm_config
        self._llm_registry = llm_registry
        self._cached_delegate: Compactor | None = None
        self._cached_config_type: str | None = None

    def compact(self, view: View) -> View | Compaction:
        """Select the best compactor for the current event stream and delegate."""
        events = list(view.events)
        config = select_compactor_config(
            events,
            llm_config=self._llm_config,
        )
        logger.info(
            'AutoCompactor selected strategy: %s for %d events',
            config.type,
            len(events),
        )
        # Reuse cached delegate when the strategy type hasn't changed.
        if config.type != self._cached_config_type:
            self._cached_delegate = Compactor.from_config(config, self._llm_registry)
            self._cached_config_type = config.type
        delegate = self._cached_delegate
        if delegate is None:
            raise RuntimeError('Compactor.from_config returned None')
        return delegate.compact(view)

    @classmethod
    def from_config(cls, config: Any, llm_registry: LLMRegistry) -> AutoCompactor:
        llm_config: object | None = None
        if config.llm_config is not None:
            # Pass through either a named config section (str) or an LLMConfig instance.
            # This ensures LLM-based compactors inherit the *primary* LLM configuration
            # instead of treating a model id as a config-section name.
            llm_config = config.llm_config
        return cls(llm_config=llm_config, llm_registry=llm_registry)


def _register_config():
    from backend.core.config.compactor_config import AutoCompactorConfig

    AutoCompactor.register_config(AutoCompactorConfig)


_register_config()
