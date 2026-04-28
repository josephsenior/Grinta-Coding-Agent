"""Framework for compacting event histories before passing them to the LLM."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from backend.context.view import View
from backend.core.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction
from backend.ledger.compaction import EventCompactor
from backend.ledger.serialization.event import event_to_dict

if TYPE_CHECKING:
    from backend.core.config.compactor_config import CompactorConfig
    from backend.inference.llm import LLM
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State


COMPACTOR_METADATA_KEY = 'compactor_meta'
"""Key identifying where metadata is stored in a ``State`` object's ``extra_data`` field."""

# Maximum number of condensation metadata batches to retain.
# Older batches become irrelevant once their events are pruned.
MAX_COMPACTOR_META_BATCHES: int = 50


def get_compaction_metadata(state: State) -> list[dict[str, Any]]:
    """Utility function to retrieve a list of metadata batches from a `State`.

    Args:
        state: The state to retrieve metadata from.

    Returns:
        list[dict[str, Any]]: A list of metadata batches, each representing a condensation.

    """
    if COMPACTOR_METADATA_KEY in state.extra_data:
        return state.extra_data[COMPACTOR_METADATA_KEY]
    return []


COMPACTOR_REGISTRY: dict[type[CompactorConfig], type[Compactor]] = {}
"""Registry of compactor configurations to their corresponding compactor classes."""


class Compaction(BaseModel):
    """Produced by a compactor to indicate the history has been compacted."""

    action: CondensationAction


class Compactor(ABC):
    """Abstract compactor interface.

    Compactors take a list of `Event` objects and reduce them into a potentially smaller list.

    Agents can use compactors to reduce the amount of events they need to consider when deciding which action to take. To use a compactor, agents can call the `compacted_history` method on the current `State` being considered and use the results instead of the full history.

    If the compactor returns a `Compaction` instead of a `View`, the agent should return `Compaction.action` instead of producing its own action. On the next agent step the compactor will use that compaction event to produce a new `View`.
    """

    def __init__(self) -> None:
        """Prepare metadata containers for a new compaction cycle."""
        self._metadata_batch: dict[str, Any] = {}
        self._llm_metadata: dict[str, Any] = {}

    def add_metadata(self, key: str, value: Any) -> None:
        """Add information to the current metadata batch.

        Any key/value pairs added to the metadata batch will be recorded in the `State` at the end of the current compaction.

        Args:
            key: The key to store the metadata under.

            value: The metadata to store.

        """
        self._metadata_batch[key] = value

    def write_metadata(self, state: State) -> None:
        """Write the current batch of metadata to the `State`.

        Resets the current metadata batch: any metadata added after this call
        will be stored in a new batch and written to the `State` at the end of
        the next compaction.

        Older metadata batches are evicted when the list exceeds
        ``MAX_COMPACTOR_META_BATCHES`` to prevent unbounded memory growth
        during very long sessions with many compaction cycles.
        """
        if COMPACTOR_METADATA_KEY not in state.extra_data:
            state.set_extra(
                COMPACTOR_METADATA_KEY, [], source='Compactor.write_metadata'
            )
        if self._metadata_batch:
            state.extra_data[COMPACTOR_METADATA_KEY].append(self._metadata_batch)
        # Evict oldest batches to bound memory
        meta_list = state.extra_data[COMPACTOR_METADATA_KEY]
        if len(meta_list) > MAX_COMPACTOR_META_BATCHES:
            state.set_extra(
                COMPACTOR_METADATA_KEY,
                meta_list[-MAX_COMPACTOR_META_BATCHES:],
                source='Compactor.write_metadata.evict',
            )
        self._metadata_batch = {}

    @contextmanager
    def metadata_batch(self, state: State):
        """Context manager to ensure batched metadata is always written to the `State`."""
        try:
            yield
        finally:
            self.write_metadata(state)

    @abstractmethod
    def compact(self, view: View) -> View | Compaction:
        """Compact a sequence of events into a potentially smaller list.

        New compactor strategies should override this method to implement their own compaction logic. Call `self.add_metadata` in the implementation to record any relevant per-compaction diagnostic information.

        Args:
            view: A view of the history containing all events that should be compacted.

        Returns:
            View | Compaction: A compacted view of the events or an event indicating the history has been compacted.

        """

    def compacted_history(self, state: State) -> View | Compaction:
        """Compact the state's history."""
        model_name = self.llm.config.model if hasattr(self, 'llm') else 'unknown'
        self._llm_metadata = state.to_llm_metadata(
            model_name=model_name, agent_name='compactor'
        )
        with self.metadata_batch(state):
            return self.compact(state.view)

    @property
    def llm_metadata(self) -> dict[str, Any]:
        """Metadata to be passed to the LLM when using this compactor.

        This metadata is used to provide context about the compaction process and can be used by the LLM to understand how the history was compacted.
        """
        if not self._llm_metadata:
            logger.warning(
                'LLM metadata is empty. Ensure to set it in the compactor implementation.'
            )
        return self._llm_metadata

    @classmethod
    def register_config(cls, configuration_type: type[CompactorConfig]) -> None:
        """Register a new compactor configuration type.

        Instances of registered configuration types can be passed to `from_config` to create instances of the corresponding compactor.

        Args:
            configuration_type: The type of configuration used to create instances of the compactor.

        Raises:
            ValueError: If the configuration type is already registered.

        """
        if configuration_type in COMPACTOR_REGISTRY:
            msg = f'Compactor configuration {configuration_type} is already registered'
            raise ValueError(msg)
        COMPACTOR_REGISTRY[configuration_type] = cls

    @classmethod
    def from_config(
        cls, config: CompactorConfig, llm_registry: LLMRegistry
    ) -> Compactor:
        """Create a compactor from a configuration object.

        Args:
            config: Configuration for the compactor.
            llm_registry: Registry of LLM instances.

        Returns:
            Compactor: A compactor instance.

        Raises:
            ValueError: If the compactor type is not recognized.

        """
        try:
            compactor_class = COMPACTOR_REGISTRY[type(config)]
            return compactor_class.from_config(config, llm_registry)
        except KeyError as e:
            msg = f'Unknown compactor config: {config}'
            raise ValueError(msg) from e


class RollingCompactor(Compactor, ABC):
    """Base class for a specialized compactor strategy that applies compaction to a rolling history.

    The rolling history is generated by `View.from_events`, which analyzes all events in the history and produces a `View` object representing what will be sent to the LLM.

    If `should_compact` says so, the compactor is then responsible for generating a `Compaction` object from the `View` object. This will be added to the event history which should -- when given to `get_view` -- produce the compacted `View` to be passed to the LLM.
    """

    # Subclasses (or from_config) may set this from config.token_budget.
    token_budget: int | None = None

    # Shared compactor instance — rules are stateless.
    _compactor: EventCompactor = EventCompactor()

    @abstractmethod
    def should_compact(self, view: View) -> bool:
        """Determine if a view should be compacted."""

    @abstractmethod
    def get_compaction(self, view: View) -> View | Compaction:
        """Get the compaction from a view."""


class BaseLLMCompactor(RollingCompactor, ABC):
    """Base class for compactors that use an LLM.

    Provides common initialization and configuration logic for LLM-based compactors.
    """

    def __init__(
        self,
        llm: LLM | None,
        max_size: int = 100,
        keep_first: int = 1,
        max_event_length: int = 10000,
    ) -> None:
        """Initialize the LLM-based compactor.

        Args:
            llm: Language model instance for generating summaries or scoring.
            max_size: Maximum number of events before condensation is triggered.
            keep_first: Number of initial events to always preserve.
            max_event_length: Maximum character length for individual event content.
        """
        if max_size < 1:
            msg = f'max_size ({max_size}) must be positive'
            raise ValueError(msg)
        if keep_first < 0:
            msg = f'keep_first ({keep_first}) cannot be negative'
            raise ValueError(msg)
        if keep_first > max_size // 2 and max_size > 1:
            # Only check if max_size is large enough to have a middle
            msg = f'keep_first ({keep_first}) must be at most half of max_size ({max_size})'
            raise ValueError(msg)

        self.llm = llm
        self.max_size = max_size
        self.keep_first = keep_first
        self.max_event_length = max_event_length
        super().__init__()
        self._validate_llm()

    def _validate_llm(self) -> None:
        """Hook for subclasses to validate LLM capabilities during initialization."""

    @classmethod
    def from_config(
        cls,
        config: Any,
        llm_registry: LLMRegistry,
    ) -> BaseLLMCompactor:
        """Create a compactor from a configuration object.

        Args:
            config: Configuration for the compactor.
            llm_registry: Registry of LLM instances.

        Returns:
            BaseLLMCompactor: A compactor instance.
        """
        llm_instance: LLM | None = None
        if hasattr(config, 'llm_config') and config.llm_config:
            from backend.core.config.llm_config import LLMConfig

            if isinstance(config.llm_config, LLMConfig):
                llm_config_obj = config.llm_config
                service_id = f'compactor_{llm_config_obj.model}'
            else:
                llm_config_obj = llm_registry.config.get_llm_config(config.llm_config)
                service_id = f'compactor_{config.llm_config}'

            # Ensure caching is disabled for compactor LLM to avoid overhead
            llm_config_obj = llm_config_obj.model_copy()
            llm_config_obj.caching_prompt = False
            llm_instance = llm_registry.get_llm(
                service_id=service_id, config=llm_config_obj
            )

        compactor = cls(
            llm=llm_instance,
            max_size=getattr(config, 'max_size', 100),
            keep_first=getattr(config, 'keep_first', 1),
            **cls._get_extra_config_args(config),
        )
        compactor.token_budget = getattr(config, 'token_budget', None)
        # If no explicit token_budget was configured but the LLM reports its context
        # size, derive a safe 80% budget so _exceeds_token_budget() is active by
        # default for any LLM-backed compactor. This prevents large single-event
        # observations (e.g. 50K-char bash output) from overflowing the context
        # window before the event-count threshold is reached.
        if compactor.token_budget is None and llm_instance is not None:
            max_input = getattr(
                getattr(llm_instance, 'config', None), 'max_input_tokens', None
            )
            if max_input:
                compactor.token_budget = int(max_input * 0.80)
        return compactor

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        """Get extra configuration arguments for the compactor constructor.

        Subclasses should override this to provide additional arguments from the config.
        """
        extra_args = {}
        if hasattr(config, 'max_event_length'):
            extra_args['max_event_length'] = config.max_event_length
        return extra_args

    def should_compact(self, view: View) -> bool:
        """Check if compaction should occur based on max_size.

        Args:
            view: Current event view

        Returns:
            True if should compact

        """
        return len(view) > self.max_size

    def _add_response_metadata(self, response: Any) -> None:
        """Add LLM response metadata to the compactor's metadata batch."""
        from backend.core.pydantic_compat import model_dump_with_options

        self.add_metadata('response', model_dump_with_options(response))
        if hasattr(self, 'llm') and self.llm:
            self.add_metadata('metrics', self.llm.metrics.get())

    def _create_compaction_result(
        self, pruned_events: list[Event], summary: str
    ) -> Compaction:
        """Create a compaction result from pruned events and a summary string."""
        summary = self._sanitize_workspace_paths(summary)
        return Compaction(
            action=CondensationAction(
                pruned_events_start_id=min(event.id for event in pruned_events),
                pruned_events_end_id=max(event.id for event in pruned_events),
                summary=summary,
                summary_offset=self.keep_first,
            ),
        )

    @staticmethod
    def _sanitize_workspace_paths(text: str) -> str:
        """Strip real workspace temp paths that may appear in LLM-generated summaries.

        When ``APP_WORKSPACE_DIR`` is set in the environment the replacement is
        precise — only the exact known path is substituted, avoiding false
        positives on unrelated text that happens to contain "app_workspace".
        When the env var is absent (e.g. in unit tests) a fuzzy regex falls back
        to matching any path-like token containing "app_workspace".
        """
        import os
        import re

        # ── Precise replacement using the known workspace path ──────────────
        ws_dir = os.environ.get('APP_WORKSPACE_DIR', '')
        if ws_dir and 'app_workspace' in ws_dir:
            ws_fwd = ws_dir.replace('\\', '/')
            ws_back = ws_dir.replace('/', '\\')
            ws_dbl = ws_back.replace('\\', '\\\\')
            # Replace longest/most-specific variants first to avoid partial matches.
            for token in (ws_dbl, ws_back, ws_fwd, ws_dir):
                if token:
                    text = text.replace(token, '[project]')
            return text

        # ── Fuzzy fallback when env var is unavailable ──────────────────────
        if 'app_workspace' not in text:
            return text
        # Full paths with drive letter or Unix root.
        text = re.sub(
            r'(?:[A-Za-z]:[/\\]|/)\S*app_workspace\S*',
            '[project]',
            text,
        )
        # Bare references without a leading path root.
        if 'app_workspace' in text:
            text = re.sub(r'app_workspace\S*', '[project]', text)
        return text

    def _truncate(self, content: str) -> str:
        """Truncate the content to fit within the specified maximum event length."""
        from backend.ledger.serialization.event import truncate_content

        return truncate_content(content, max_chars=self.max_event_length)

    # ------------------------------------------------------------------ #
    # Token-aware helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def estimate_view_tokens(view: View) -> int:
        """Estimate the total token count of a view.

        Uses a best-effort tokenizer when available (``tiktoken``), and
        falls back to ``len(text) // 4``.
        """
        payload_parts: list[str] = []
        for event in view.events:
            try:
                payload_parts.append(json.dumps(event_to_dict(event), default=str))
            except Exception:
                payload_parts.append(str(getattr(event, 'message', '')))

        text = '\n'.join(payload_parts)
        if not text:
            return 1

        tokenizer = BaseLLMCompactor._get_tokenizer()
        if tokenizer is not None:
            try:
                return max(1, len(tokenizer.encode(text)))
            except Exception:
                pass
        return max(1, len(text) // 4)

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_tokenizer():
        try:
            import tiktoken  # type: ignore

            return tiktoken.get_encoding('cl100k_base')
        except Exception:
            return None

    def _model_token_multiplier(self) -> float:
        """Return a correction factor to compensate for tokenizer family mismatch.

        ``estimate_view_tokens`` always uses ``cl100k_base`` (GPT family).
        Claude-family models diverge by ~5% on prose and up to ~20% on
        dense code, so we apply the same 1.05x correction used by the prompt
        builder when the active model is a Claude variant.
        """
        model: str = ''
        try:
            model = str(getattr(getattr(getattr(self, 'llm', None), 'config', None), 'model', '') or '')
        except Exception:
            pass
        from backend.inference.provider_capabilities import model_token_correction
        factor, _ = model_token_correction(model)
        return factor

    def _exceeds_token_budget(self, view: View) -> bool:
        """Return True when a token_budget is set and the view exceeds it."""
        if self.token_budget is None:
            return False
        raw = self.estimate_view_tokens(view)
        estimated = int(raw * self._model_token_multiplier())
        if estimated > self.token_budget:
            logger.debug(
                'Token budget exceeded: %d estimated (×%.2f) > %d budget',
                estimated,
                self._model_token_multiplier(),
                self.token_budget,
            )
            return True
        return False

    def compact(self, view: View) -> View | Compaction:
        """Compact, then compact further if thresholds are exceeded."""
        compacted = self._compactor.compact(view.events)
        if len(compacted) < len(view.events):
            view = View(events=compacted)
        should = self.should_compact(view)
        budget = self._exceeds_token_budget(view)
        logger.debug(
            'compact check: len(view)=%d max_size=%d should_compact=%s token_budget=%s exceeds_budget=%s',
            len(view),
            self.max_size,
            should,
            self.token_budget,
            budget,
        )
        if should or budget:
            return self.get_compaction(view)
        return view


# Resolve forward references once CondensationAction is defined at import time.
Compaction.model_rebuild()

__all__ = [
    'COMPACTOR_METADATA_KEY',
    'COMPACTOR_REGISTRY',
    'Compaction',
    'Compactor',
    'RollingCompactor',
    'BaseLLMCompactor',
    'get_compaction_metadata',
]
