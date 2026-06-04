"""Compactor that automatically selects the best strategy for the current session."""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.inference.llm_registry import LLMRegistry

from backend.context.compactor.compactor import Compaction, Compactor, RollingCompactor
from backend.context.compactor.strategies.auto_selector import select_compactor_config
from backend.context.view import View
from backend.core.config.compactor_config import (
    AmortizedPruningCompactorConfig,
    CompactorConfig,
    SmartCompactorConfig,
    StructuredSummaryCompactorConfig,
)
from backend.core.logger import app_logger as logger


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
        allow_llm_hot_path: bool = False,
    ) -> None:
        super().__init__()
        # NOTE: This is intentionally *not* just a model string.
        # It can be either:
        # - an LLMConfig instance (preferred; inherits the primary model + keys)
        # - a named LLM config section (e.g. "llm")
        self._llm_config = llm_config
        self._llm_registry = llm_registry
        self._allow_llm_hot_path = allow_llm_hot_path
        self._cached_delegate: Compactor | None = None
        self._cached_config_key: str | None = None

    async def compact(self, view: View) -> View | Compaction:
        """Select the best compactor for the current event stream and delegate."""
        started = time.perf_counter()
        events = list(view.events)
        explicit_request = bool(
            getattr(view, 'unhandled_condensation_request', False)
        )
        config = (
            self._select_explicit_request_config(len(events))
            if explicit_request
            else select_compactor_config(
                events,
                llm_config=self._llm_config,
                allow_llm_hot_path=self._allow_llm_hot_path,
            )
        )
        logger.info(
            'AutoCompactor selected strategy: %s for %d events '
            '(explicit_request=%s allow_llm_hot_path=%s)',
            config.type,
            len(events),
            explicit_request,
            self._allow_llm_hot_path,
        )
        delegate = self._delegate_for_config(config, explicit_request)
        result = await delegate.compact(view)
        if explicit_request and isinstance(result, View):
            result = await self._force_delegate_compaction(delegate, result)
        elapsed = time.perf_counter() - started
        logger.info(
            'AutoCompactor finished strategy=%s result=%s events=%d elapsed=%.3fs',
            config.type,
            type(result).__name__,
            len(events),
            elapsed,
        )
        return result

    def should_emit_compaction_status(self, view: View) -> bool:
        """Predict whether this auto-selection will produce a condensation action."""
        events = list(view.events)
        if getattr(view, 'unhandled_condensation_request', False):
            return True
        config = select_compactor_config(
            events,
            llm_config=self._llm_config,
            allow_llm_hot_path=self._allow_llm_hot_path,
        )
        return self._config_emits_compaction_action(config, len(events))

    @staticmethod
    def _config_emits_compaction_action(
        config: CompactorConfig,
        event_count: int,
    ) -> bool:
        config_type = getattr(config, 'type', '')
        if config_type in {'amortized', 'structured', 'smart'}:
            return event_count > int(getattr(config, 'max_size', 0) or 0)
        return False

    def _select_explicit_request_config(self, event_count: int) -> CompactorConfig:
        """Pick a real compactor for provider context-limit recovery."""
        max_size = max(2, min(200, event_count or 2))
        keep_first = min(5, max_size // 2)
        if self._llm_config is not None:
            return StructuredSummaryCompactorConfig(
                llm_config=self._llm_config,
                max_size=max_size,
                keep_first=keep_first,
            )
        return self._deterministic_explicit_request_config(event_count)

    @staticmethod
    def _deterministic_explicit_request_config(
        event_count: int,
    ) -> AmortizedPruningCompactorConfig:
        max_size = max(4, min(150, event_count or 4))
        keep_first = min(3, max(0, (max_size // 2) - 1))
        return AmortizedPruningCompactorConfig(
            max_size=max_size,
            keep_first=keep_first,
        )

    def _delegate_for_config(
        self, config: CompactorConfig, explicit_request: bool
    ) -> Compactor:
        try:
            return self._cached_or_create_delegate(config)
        except Exception as exc:
            if not explicit_request:
                raise
            logger.warning(
                'AutoCompactor explicit-request strategy %s unavailable (%s); '
                'falling back to a simpler recovery compactor.',
                config.type,
                exc,
            )
            if self._llm_config is not None and config.type == 'structured':
                llm_fallback = self._smart_explicit_request_config(config)
                with contextlib.suppress(Exception):
                    return self._cached_or_create_delegate(llm_fallback)
            deterministic_fallback = self._deterministic_explicit_request_config(
                getattr(config, 'max_size', 0)
            )
            return self._cached_or_create_delegate(deterministic_fallback)

    def _smart_explicit_request_config(
        self, config: CompactorConfig
    ) -> SmartCompactorConfig:
        max_size = max(2, int(getattr(config, 'max_size', 200) or 200))
        keep_first = min(int(getattr(config, 'keep_first', 5) or 0), max_size // 2)
        return SmartCompactorConfig(
            llm_config=self._llm_config,
            max_size=max_size,
            keep_first=keep_first,
        )

    def _cached_or_create_delegate(self, config: CompactorConfig) -> Compactor:
        cache_key = self._cache_key(config)
        if cache_key != self._cached_config_key:
            self._cached_delegate = Compactor.from_config(config, self._llm_registry)
            self._cached_config_key = cache_key
        delegate = self._cached_delegate
        if delegate is None:
            raise RuntimeError('Compactor.from_config returned None')
        return delegate

    @staticmethod
    def _cache_key(config: CompactorConfig) -> str:
        with contextlib.suppress(Exception):
            return config.model_dump_json()
        return repr(config)

    async def _force_delegate_compaction(
        self, delegate: Compactor, view: View
    ) -> View | Compaction:
        if isinstance(delegate, RollingCompactor):
            logger.info('AutoCompactor forcing delegate compaction for explicit request')
            return await delegate.get_compaction(view)
        return view

    @classmethod
    def from_config(cls, config: Any, llm_registry: LLMRegistry) -> AutoCompactor:
        llm_config: object | None = None
        if config.llm_config is not None:
            # Pass through either a named config section (str) or an LLMConfig instance.
            # This ensures LLM-based compactors inherit the *primary* LLM configuration
            # instead of treating a model id as a config-section name.
            llm_config = config.llm_config
        return cls(
            llm_config=llm_config,
            llm_registry=llm_registry,
            allow_llm_hot_path=bool(getattr(config, 'allow_llm_hot_path', False)),
        )


def _register_config():
    from backend.core.config.compactor_config import AutoCompactorConfig

    AutoCompactor.register_config(AutoCompactorConfig)


_register_config()
