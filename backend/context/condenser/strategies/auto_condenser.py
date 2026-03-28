"""Condenser that automatically selects the best strategy for the current session."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.condenser_config import AutoCondenserConfig
    from backend.inference.llm_registry import LLMRegistry

from backend.context.condenser.condenser import Condensation, Condenser
from backend.context.condenser.strategies.auto_selector import select_condenser_config
from backend.context.view import View

logger = logging.getLogger(__name__)


class AutoCondenser(Condenser):
    """Analyses the event stream and delegates to the most appropriate condenser.

    On each ``condense()`` call the auto-selector inspects the current events
    and picks a strategy (noop, observation_masking, structured_summary, etc.).
    A delegate condenser is then instantiated from the selected config and the
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
        self._cached_delegate: Condenser | None = None
        self._cached_config_type: str | None = None

    def condense(self, view: View) -> View | Condensation:
        """Select the best condenser for the current event stream and delegate."""
        events = list(view.events)
        config = select_condenser_config(
            events,
            llm_config=self._llm_config,
        )
        logger.info(
            "AutoCondenser selected strategy: %s for %d events",
            config.type,
            len(events),
        )
        # Reuse cached delegate when the strategy type hasn't changed.
        if config.type != self._cached_config_type:
            self._cached_delegate = Condenser.from_config(config, self._llm_registry)
            self._cached_config_type = config.type
        delegate = self._cached_delegate
        if delegate is None:
            raise RuntimeError("Condenser.from_config returned None")
        return delegate.condense(view)

    @classmethod
    def from_config(
        cls, config: AutoCondenserConfig, llm_registry: LLMRegistry
    ) -> AutoCondenser:
        llm_config: object | None = None
        if config.llm_config is not None:
            # Pass through either a named config section (str) or an LLMConfig instance.
            # This ensures LLM-based condensers inherit the *primary* LLM configuration
            # instead of treating a model id as a config-section name.
            llm_config = config.llm_config
        return cls(llm_config=llm_config, llm_registry=llm_registry)


def _register_config():
    from backend.core.config.condenser_config import AutoCondenserConfig

    AutoCondenser.register_config(AutoCondenserConfig)


_register_config()
