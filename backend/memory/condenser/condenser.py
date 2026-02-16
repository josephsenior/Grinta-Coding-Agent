"""Framework for condensing event histories before passing them to the LLM."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from backend.core.logger import FORGE_logger as logger
from backend.events.action.agent import CondensationAction
from backend.events.compaction import EventCompactor
from backend.events.serialization.event import event_to_dict
from backend.memory.view import View

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.core.config.condenser_config import CondenserConfig
    from backend.events.event import Event
    from backend.llm.llm import LLM
    from backend.llm.llm_registry import LLMRegistry


CONDENSER_METADATA_KEY = "condenser_meta"
"""Key identifying where metadata is stored in a ``State`` object's ``extra_data`` field."""

# Maximum number of condensation metadata batches to retain.
# Older batches become irrelevant once their events are forgotten.
MAX_CONDENSER_META_BATCHES: int = 50


def get_condensation_metadata(state: State) -> list[dict[str, Any]]:
    """Utility function to retrieve a list of metadata batches from a `State`.

    Args:
        state: The state to retrieve metadata from.

    Returns:
        list[dict[str, Any]]: A list of metadata batches, each representing a condensation.

    """
    if CONDENSER_METADATA_KEY in state.extra_data:
        return state.extra_data[CONDENSER_METADATA_KEY]
    return []


CONDENSER_REGISTRY: dict[type[CondenserConfig], type[Condenser]] = {}
"Registry of condenser configurations to their corresponding condenser classes."


class Condensation(BaseModel):
    """Produced by a condenser to indicate the history has been condensed."""

    action: CondensationAction


class Condenser(ABC):
    """Abstract condenser interface.

    Condensers take a list of `Event` objects and reduce them into a potentially smaller list.

    Agents can use condensers to reduce the amount of events they need to consider when deciding which action to take. To use a condenser, agents can call the `condensed_history` method on the current `State` being considered and use the results instead of the full history.

    If the condenser returns a `Condensation` instead of a `View`, the agent should return `Condensation.action` instead of producing its own action. On the next agent step the condenser will use that condensation event to produce a new `View`.
    """

    def __init__(self) -> None:
        """Prepare metadata containers for a new condensation cycle."""
        self._metadata_batch: dict[str, Any] = {}
        self._llm_metadata: dict[str, Any] = {}

    def add_metadata(self, key: str, value: Any) -> None:
        """Add information to the current metadata batch.

        Any key/value pairs added to the metadata batch will be recorded in the `State` at the end of the current condensation.

        Args:
            key: The key to store the metadata under.

            value: The metadata to store.

        """
        self._metadata_batch[key] = value

    def write_metadata(self, state: State) -> None:
        """Write the current batch of metadata to the `State`.

        Resets the current metadata batch: any metadata added after this call
        will be stored in a new batch and written to the `State` at the end of
        the next condensation.

        Older metadata batches are evicted when the list exceeds
        ``MAX_CONDENSER_META_BATCHES`` to prevent unbounded memory growth
        during very long sessions with many condensation cycles.
        """
        if CONDENSER_METADATA_KEY not in state.extra_data:
            state.set_extra(
                CONDENSER_METADATA_KEY, [], source="Condenser.write_metadata"
            )
        if self._metadata_batch:
            state.extra_data[CONDENSER_METADATA_KEY].append(self._metadata_batch)
        # Evict oldest batches to bound memory
        meta_list = state.extra_data[CONDENSER_METADATA_KEY]
        if len(meta_list) > MAX_CONDENSER_META_BATCHES:
            state.set_extra(
                CONDENSER_METADATA_KEY,
                meta_list[-MAX_CONDENSER_META_BATCHES:],
                source="Condenser.write_metadata.evict",
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
    def condense(self, View) -> View | Condensation:
        """Condense a sequence of events into a potentially smaller list.

        New condenser strategies should override this method to implement their own condensation logic. Call `self.add_metadata` in the implementation to record any relevant per-condensation diagnostic information.

        Args:
            View: A view of the history containing all events that should be condensed.

        Returns:
            View | Condensation: A condensed view of the events or an event indicating the history has been condensed.

        """

    def condensed_history(self, state: State) -> View | Condensation:
        """Condense the state's history."""
        model_name = self.llm.config.model if hasattr(self, "llm") else "unknown"
        self._llm_metadata = state.to_llm_metadata(
            model_name=model_name, agent_name="condenser"
        )
        with self.metadata_batch(state):
            return self.condense(state.view)

    @property
    def llm_metadata(self) -> dict[str, Any]:
        """Metadata to be passed to the LLM when using this condenser.

        This metadata is used to provide context about the condensation process and can be used by the LLM to understand how the history was condensed.
        """
        if not self._llm_metadata:
            logger.warning(
                "LLM metadata is empty. Ensure to set it in the condenser implementation."
            )
        return self._llm_metadata

    @classmethod
    def register_config(cls, configuration_type: type[CondenserConfig]) -> None:
        """Register a new condenser configuration type.

        Instances of registered configuration types can be passed to `from_config` to create instances of the corresponding condenser.

        Args:
            configuration_type: The type of configuration used to create instances of the condenser.

        Raises:
            ValueError: If the configuration type is already registered.

        """
        if configuration_type in CONDENSER_REGISTRY:
            msg = f"Condenser configuration {configuration_type} is already registered"
            raise ValueError(msg)
        CONDENSER_REGISTRY[configuration_type] = cls

    @classmethod
    def from_config(
        cls, config: CondenserConfig, llm_registry: LLMRegistry
    ) -> Condenser:
        """Create a condenser from a configuration object.

        Args:
            config: Configuration for the condenser.
            llm_registry: Registry of LLM instances.

        Returns:
            Condenser: A condenser instance.

        Raises:
            ValueError: If the condenser type is not recognized.

        """
        try:
            condenser_class = CONDENSER_REGISTRY[type(config)]
            return condenser_class.from_config(config, llm_registry)
        except KeyError as e:
            msg = f"Unknown condenser config: {config}"
            raise ValueError(msg) from e


class RollingCondenser(Condenser, ABC):
    """Base class for a specialized condenser strategy that applies condensation to a rolling history.

    The rolling history is generated by `View.from_events`, which analyzes all events in the history and produces a `View` object representing what will be sent to the LLM.

    If `should_condense` says so, the condenser is then responsible for generating a `Condensation` object from the `View` object. This will be added to the event history which should -- when given to `get_view` -- produce the condensed `View` to be passed to the LLM.
    """

    # Subclasses (or from_config) may set this from config.token_budget.
    token_budget: int | None = None

    # Shared compactor instance — rules are stateless.
    _compactor: EventCompactor = EventCompactor()

    @abstractmethod
    def should_condense(self, view: View) -> bool:
        """Determine if a view should be condensed."""

    @abstractmethod
    def get_condensation(self, view: View) -> Condensation:
        """Get the condensation from a view."""


class BaseLLMCondenser(RollingCondenser, ABC):
    """Base class for condensers that use an LLM.

    Provides common initialization and configuration logic for LLM-based condensers.
    """

    def __init__(
        self,
        llm: LLM | None,
        max_size: int = 100,
        keep_first: int = 1,
        max_event_length: int = 10000,
    ) -> None:
        """Initialize the LLM-based condenser.

        Args:
            llm: Language model instance for generating summaries or scoring.
            max_size: Maximum number of events before condensation is triggered.
            keep_first: Number of initial events to always preserve.
            max_event_length: Maximum character length for individual event content.
        """
        if max_size < 1:
            msg = f"max_size ({max_size}) must be positive"
            raise ValueError(msg)
        if keep_first < 0:
            msg = f"keep_first ({keep_first}) cannot be negative"
            raise ValueError(msg)
        if keep_first >= max_size // 2 and max_size > 1:
            # Only check if max_size is large enough to have a middle
            msg = f"keep_first ({keep_first}) must be less than half of max_size ({max_size})"
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
    ) -> BaseLLMCondenser:
        """Create a condenser from a configuration object.

        Args:
            config: Configuration for the condenser.
            llm_registry: Registry of LLM instances.

        Returns:
            BaseLLMCondenser: A condenser instance.
        """
        llm_instance: LLM | None = None
        if hasattr(config, "llm_config") and config.llm_config:
            from backend.core.config.llm_config import LLMConfig

            if isinstance(config.llm_config, LLMConfig):
                llm_config_obj = config.llm_config
                service_id = f"condenser_{llm_config_obj.model}"
            else:
                llm_config_obj = llm_registry.config.get_llm_config(config.llm_config)
                service_id = f"condenser_{config.llm_config}"

            # Ensure caching is disabled for condenser LLM to avoid overhead
            llm_config_obj = llm_config_obj.model_copy()
            llm_config_obj.caching_prompt = False
            llm_instance = llm_registry.get_llm(
                service_id=service_id, config=llm_config_obj
            )

        condenser = cls(
            llm=llm_instance,
            max_size=getattr(config, "max_size", 100),
            keep_first=getattr(config, "keep_first", 1),
            **cls._get_extra_config_args(config),
        )
        condenser.token_budget = getattr(config, "token_budget", None)
        return condenser

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        """Get extra configuration arguments for the condenser constructor.

        Subclasses should override this to provide additional arguments from the config.
        """
        extra_args = {}
        if hasattr(config, "max_event_length"):
            extra_args["max_event_length"] = config.max_event_length
        return extra_args

    def should_condense(self, view: View) -> bool:
        """Check if condensation should occur based on max_size.

        Args:
            view: Current event view

        Returns:
            True if should condense

        """
        return len(view) > self.max_size

    def _add_response_metadata(self, response: Any) -> None:
        """Add LLM response metadata to the condenser's metadata batch."""
        from backend.core.pydantic_compat import model_dump_with_options

        self.add_metadata("response", model_dump_with_options(response))
        if hasattr(self, "llm") and self.llm:
            self.add_metadata("metrics", self.llm.metrics.get())

    def _create_condensation_result(
        self, forgotten_events: list[Event], summary: str
    ) -> Condensation:
        """Create a condensation result from forgotten events and a summary string."""
        return Condensation(
            action=CondensationAction(
                forgotten_events_start_id=min(event.id for event in forgotten_events),
                forgotten_events_end_id=max(event.id for event in forgotten_events),
                summary=summary,
                summary_offset=self.keep_first,
            ),
        )

    def _truncate(self, content: str) -> str:
        """Truncate the content to fit within the specified maximum event length."""
        from backend.events.serialization.event import truncate_content

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
                payload_parts.append(str(getattr(event, "message", "")))

        text = "\n".join(payload_parts)
        if not text:
            return 1

        tokenizer = BaseLLMCondenser._get_tokenizer()
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

            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None

    def _exceeds_token_budget(self, view: View) -> bool:
        """Return True when a token_budget is set and the view exceeds it."""
        if self.token_budget is None:
            return False
        estimated = self.estimate_view_tokens(view)
        if estimated > self.token_budget:
            logger.debug(
                "Token budget exceeded: %d estimated > %d budget",
                estimated,
                self.token_budget,
            )
            return True
        return False

    def condense(self, view: View) -> View | Condensation:
        """Compact, then condense if thresholds are exceeded."""
        compacted = self._compactor.compact(view.events)
        if len(compacted) < len(view.events):
            view = View(events=compacted)
        if self.should_condense(view) or self._exceeds_token_budget(view):
            return self.get_condensation(view)
        return view


# Resolve forward references once CondensationAction is defined at import time.
Condensation.model_rebuild()
