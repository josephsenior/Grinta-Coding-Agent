from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.core.message import Message, TextContent
from backend.ledger.action import MessageAction
from backend.inference.prompt_caching import model_supports_prompt_cache_hints
from backend.context import ContextMemory
from backend.context.compactor import Compactor
from backend.context.pre_condensation_snapshot import (
    extract_snapshot,
    format_snapshot_for_injection,
    load_snapshot,
    save_snapshot,
)
from backend.context.view import View

if TYPE_CHECKING:
    from backend.orchestration.state.state import State
    from backend.core.config import AgentConfig
    from backend.ledger.action import Action
    from backend.ledger.event import Event
    from backend.inference.llm_registry import LLMRegistry
    from backend.utils.prompt import PromptManager


@dataclass
class CondensedHistory:
    events: list[Event]
    pending_action: Action | None


class ContextMemoryManager:
    """Owns context memory and condensation."""

    def __init__(
        self,
        config: AgentConfig,
        llm_registry: LLMRegistry,
    ) -> None:
        self._config = config
        self._llm_registry = llm_registry
        self.conversation_memory: ContextMemory | None = None
        self.compactor: Compactor | None = None

    def initialize(self, prompt_manager: PromptManager) -> None:
        """Initialize context memory with prompt manager."""
        self.conversation_memory = ContextMemory(self._config, prompt_manager)
        # Initialize compactor from config if available
        compactor_config = getattr(self._config, "compactor_config", None)
        self._init_compactor(compactor_config)

    def _init_compactor(self, compactor_config) -> None:
        """Initialize the compactor from config."""
        if compactor_config is None:
            self.compactor = None
            return

        try:
            self.compactor = Compactor.from_config(
                compactor_config,
                self._llm_registry,
            )
            logger.debug("Using compactor: %s", type(self.compactor))
        except Exception as exc:  # pragma: no cover - condensation optional
            logger.warning("Failed to initialize compactor: %s", exc)
            self.compactor = None

    # --------------------------------------------------------------------- #
    # History utilities
    # --------------------------------------------------------------------- #
    def condense_history(self, state: State) -> CondensedHistory:
        history = getattr(state, "history", [])
        if not self.compactor:
            return CondensedHistory(list(history), None)

        # Auto-extract critical context before compaction may discard events
        self._extract_pre_condensation_snapshot(list(history))

        condensation_result = self.compactor.compacted_history(state)

        # If memory pressure is active and the compactor chose NOT to
        # compact (returned a plain View), force compaction so the
        # agent loop can recover from high-memory situations.
        memory_pressure = state.turn_signals.memory_pressure
        if memory_pressure and isinstance(condensation_result, View):
            from backend.context.compactor.compactor import RollingCompactor

            if isinstance(self.compactor, RollingCompactor):
                logger.info(
                    "Memory pressure %s: forcing compaction",
                    memory_pressure,
                )
                try:
                    forced = self.compactor.get_compaction(condensation_result)
                    condensation_result = forced
                except Exception as exc:
                    logger.warning("Forced compaction failed: %s", exc)
            # Clear the flag after consuming it
            state.ack_memory_pressure(source="ContextMemoryManager")

        if isinstance(condensation_result, View):
            return CondensedHistory(condensation_result.events, None)

        # Compaction occurred — attach the snapshot for post-recovery injection
        return CondensedHistory([], condensation_result.action)

    def _extract_pre_condensation_snapshot(self, history: list[Event]) -> None:
        """Extract and persist a snapshot of critical context from current history.

        This runs *before* the compactor, so the full event stream is still
        available.  The snapshot is read back during post-condensation recovery.
        """
        try:
            snapshot = extract_snapshot(history)
            if snapshot.get("files_touched") or snapshot.get("recent_errors") or snapshot.get("decisions"):
                save_snapshot(snapshot)
        except Exception:
            logger.debug("Pre-condensation snapshot extraction failed", exc_info=True)

    @staticmethod
    def get_restored_context() -> str:
        """Load and format the pre-condensation snapshot for injection into recovery.

        Returns an empty string if no snapshot is available.
        """
        snapshot = load_snapshot()
        if not snapshot:
            return ""
        return format_snapshot_for_injection(snapshot)

    def get_initial_user_message(self, events: Iterable[Event]) -> MessageAction:
        from backend.core.schemas import ActionType
        from backend.ledger.event import EventSource

        for event in events:
            try:
                source = getattr(event, "source", None)
                if source != EventSource.USER:
                    continue

                if isinstance(event, MessageAction):
                    return event

                if getattr(event, "action", None) == ActionType.MESSAGE and hasattr(
                    event, "content"
                ):
                    cloned = MessageAction(
                        content=str(getattr(event, "content", "")),
                        file_urls=getattr(event, "file_urls", None),
                        image_urls=getattr(event, "image_urls", None),
                        wait_for_response=bool(
                            getattr(event, "wait_for_response", False)
                        ),
                    )
                    cloned.source = source
                    if hasattr(event, "id"):
                        cloned.id = getattr(event, "id")
                    if hasattr(event, "timestamp"):
                        cloned.timestamp = getattr(event, "timestamp")
                    return cloned
            except Exception:
                continue
        raise ValueError("Initial user message not found")

    def build_messages(
        self,
        condensed_history: Iterable[Event],
        initial_user_message: MessageAction,
        llm_config,
    ) -> list[Message]:
        if not self.conversation_memory:
            raise RuntimeError("Conversation memory is not initialized")

        events = list(condensed_history)
        messages = self.conversation_memory.process_events(
            condensed_history=events,
            initial_user_action=initial_user_message,
            max_message_chars=getattr(llm_config, "max_message_chars", None),
            vision_is_active=getattr(llm_config, "vision_is_active", False),
        )

        if not messages:
            return messages

        model = getattr(llm_config, "model", None) or ""
        caching_on = bool(getattr(llm_config, "caching_prompt", True))
        if caching_on and model_supports_prompt_cache_hints(str(model)):
            first_message = messages[0]
            for item in first_message.content:
                if isinstance(item, TextContent):
                    item.cache_prompt = True
                    break

            for message in reversed(messages):
                if message.role == "user":
                    for item in message.content:
                        if isinstance(item, TextContent):
                            item.cache_prompt = True
                            break
                    break

        return messages
__all__ = [
    "CondensedHistory",
    "ContextMemoryManager",
]
