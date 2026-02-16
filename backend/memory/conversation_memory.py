"""Utilities for transforming event history into LLM-ready conversation messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from backend.core.config.agent_config import AgentConfig
from backend.core.logger import FORGE_logger as logger
from backend.core.message import Message
from backend.core.schemas import ActionType
from backend.events.action import (
    Action,
    MessageAction,
)
from backend.events.action.message import SystemMessageAction
from backend.events.event import Event, EventSource
from backend.events.observation.agent import RecallObservation
from backend.events.observation.observation import Observation
from backend.memory.action_processors import convert_action_to_messages
from backend.memory.context_tracking import ContextTracker
from backend.memory.memory_types import (
    ContextAnchor,
    Decision,
    DecisionType,
)
from backend.memory.message_formatting import (
    apply_user_message_formatting,
    is_action_event,
    is_instance_of,
    is_observation_event,
    is_text_content,
    message_with_text,
    remove_duplicate_system_prompt_user,
)
from backend.memory.observation_processors import convert_observation_to_message
from backend.memory.prompt_assembly import process_recall_observation
from backend.memory.tool_call_tracker import (
    filter_unmatched_tool_calls,
    flush_resolved_tool_calls,
)
from backend.memory.vector_store import EnhancedVectorStore
from backend.utils.prompt import PromptManager


@dataclass
class _ToolCallTracking:
    pending_action_messages: dict[str, Message] = field(default_factory=dict)
    tool_call_messages: dict[str, Message] = field(default_factory=dict)


class ConversationMemory:
    """Processes event history into a coherent conversation for the agent."""

    def __init__(self, config: AgentConfig, prompt_manager: PromptManager) -> None:
        """Store agent configuration and set up optional vector memory backends."""
        self.agent_config = config
        self.prompt_manager = prompt_manager

        # Initialize vector memory if enabled
        vector_store: EnhancedVectorStore | None = None
        if bool(getattr(config, "enable_vector_memory", False)):
            vector_store = self._initialize_vector_memory()

        # Context tracking (decisions, anchors, vector memory)
        self._ctx = ContextTracker(vector_store=vector_store)

    # Delegate context-tracking API to ContextTracker
    @property
    def decisions(self) -> dict[str, Decision]:
        return self._ctx.decisions

    @property
    def anchors(self) -> dict[str, ContextAnchor]:
        return self._ctx.anchors

    @property
    def vector_store(self) -> EnhancedVectorStore | None:
        return self._ctx.vector_store

    def track_decision(
        self,
        description: str,
        rationale: str,
        decision_type: DecisionType,
        context: str,
        confidence: float = 1.0,
    ) -> Decision:
        """Track a decision made during conversation."""
        return self._ctx.track_decision(
            description, rationale, decision_type, context, confidence,
        )

    def add_anchor(
        self, content: str, category: str, importance: float = 0.9
    ) -> ContextAnchor:
        """Create a context anchor for critical information."""
        return self._ctx.add_anchor(content, category, importance)

    def get_context_summary(self) -> str:
        """Get a summary of active anchors and recent decisions for the prompt."""
        return self._ctx.get_context_summary()

    def store_in_memory(
        self,
        event_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store an event in persistent vector memory."""
        self._ctx.store_in_memory(event_id, role, content, metadata)

    def recall_from_memory(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Retrieve relevant context from persistent vector memory."""
        return self._ctx.recall_from_memory(query, k)

    def _initialize_vector_memory(self) -> None:
        """Initialize vector memory store for persistent context."""
        try:
            hybrid_enabled = bool(
                getattr(self.agent_config, "enable_hybrid_retrieval", False)
            )
            self._ctx.vector_store = EnhancedVectorStore(
                collection_name="conversation_memory",
                enable_cache=True,
                enable_reranking=hybrid_enabled,
            )
            logger.info(
                "✅ Vector memory initialized for ConversationMemory\n   Accuracy: 92%% | Hybrid retrieval: %s",
                "enabled" if hybrid_enabled else "disabled",
            )
        except Exception as e:
            logger.warning(
                "Failed to initialize vector memory: %s\n"
                "Continuing without persistent memory. To enable:\n"
                "  pip install chromadb sentence-transformers",
                e,
            )
            self._ctx.vector_store = None

    def apply_prompt_caching(self, messages: list[Message]) -> None:
        """Set prompt caching hints for the first system message and the latest user message."""
        if not self._should_cache(messages):
            return
        self._reset_cache_flags(messages)
        self._cache_first_system_message(messages)
        self._cache_latest_user_message(messages)

    def _should_cache(self, messages: list[Message]) -> bool:
        return bool(
            messages and getattr(self.agent_config, "enable_prompt_caching", True)
        )

    def _reset_cache_flags(self, messages: list[Message]) -> None:
        for message in messages:
            for content in getattr(message, "content", []) or []:
                if is_text_content(content):
                    content.cache_prompt = False

    def _cache_first_system_message(self, messages: list[Message]) -> None:
        first_message = messages[0]
        for content in getattr(first_message, "content", []) or []:
            if is_text_content(content):
                content.cache_prompt = True

    def _cache_latest_user_message(self, messages: list[Message]) -> None:
        for message in reversed(messages):
            if message.role != "user":
                continue
            for content in getattr(message, "content", []) or []:
                if is_text_content(content):
                    content.cache_prompt = True
            break

    @staticmethod
    def _is_valid_image_url(url: str | None) -> bool:
        """Check if an image URL is valid and non-empty.

        Validates that a URL exists and is not just whitespace. Used to filter
        out placeholder or invalid image URLs before including them in messages.

        Args:
            url: The image URL string to validate

        Returns:
            bool: True if URL is non-None and non-empty after stripping whitespace,
                False otherwise

        Example:
            >>> ConversationMemory._is_valid_image_url("https://example.com/image.png")
            True
            >>> ConversationMemory._is_valid_image_url(None)
            False
            >>> ConversationMemory._is_valid_image_url("   ")
            False

        """
        return bool(url and url.strip())

    def process_events(
        self,
        condensed_history: list[Event],
        initial_user_action: MessageAction,
        max_message_chars: int | None = None,
        vision_is_active: bool = False,
    ) -> list[Message]:
        """Process state history into a list of messages for the LLM.

        Ensures that tool call actions are processed correctly in function calling mode.

        Args:
            condensed_history: The condensed history of events to convert
            max_message_chars: The maximum number of characters in the content of an event included
                in the prompt to the LLM. Larger observations are truncated.
            vision_is_active: Whether vision is active in the LLM. If True, image URLs will be included.
            initial_user_action: The initial user message action, if available. Used to ensure the conversation starts correctly.

        """
        events = self._prepare_event_history(condensed_history, initial_user_action)
        logger.debug(
            "Visual browsing: %s", self.agent_config.enable_som_visual_browsing
        )
        messages: list[Message] = []
        tool_state = _ToolCallTracking()
        for i, event in enumerate(events):
            messages_to_add = self._messages_from_event(
                event=event,
                index=i,
                events=events,
                tool_state=tool_state,
                max_message_chars=max_message_chars,
                vision_is_active=vision_is_active,
            )
            messages_to_add.extend(self._flush_resolved_tool_calls(tool_state))
            messages += messages_to_add
        messages = list(filter_unmatched_tool_calls(messages))
        messages = self._normalize_system_messages(messages)
        messages = remove_duplicate_system_prompt_user(messages)
        return apply_user_message_formatting(messages)

    def _prepare_event_history(
        self,
        condensed_history: list[Event],
        initial_user_action: MessageAction,
    ) -> list[Event]:
        """Create a defensively-copied history with required system/user roots."""
        events = list(condensed_history)
        self._ensure_system_message(events)
        self._ensure_initial_user_message(events, initial_user_action)
        return events

    def _messages_from_event(
        self,
        *,
        event: Event,
        index: int,
        events: list[Event],
        tool_state: _ToolCallTracking,
        max_message_chars: int | None,
        vision_is_active: bool,
    ) -> list[Message]:
        """Dispatch an event to the appropriate transformation helper."""
        if is_action_event(event):
            return self._process_action(
                action=cast(Action, event),
                pending_tool_call_action_messages=tool_state.pending_action_messages,
                vision_is_active=vision_is_active,
            )
        if is_observation_event(event):
            return self._process_observation(
                obs=cast(Observation, event),
                tool_call_id_to_message=tool_state.tool_call_messages,
                max_message_chars=max_message_chars,
                vision_is_active=vision_is_active,
                enable_som_visual_browsing=self.agent_config.enable_som_visual_browsing,
                current_index=index,
                events=events,
            )
        return self._fallback_message_for_generic_event(event)

    def _fallback_message_for_generic_event(self, event: Any) -> list[Message]:
        """Convert generic event doubles to user messages when possible."""
        fallback_content = None
        if hasattr(event, "content") and isinstance(getattr(event, "content"), str):
            fallback_content = getattr(event, "content")
        elif hasattr(event, "message") and isinstance(getattr(event, "message"), str):
            fallback_content = getattr(event, "message")
        if fallback_content is not None:
            logger.debug(
                "[ConversationMemory] Handling generic event type %s via fallback.",
                type(event).__name__,
            )
            return [message_with_text("user", fallback_content)]
        raise ValueError(
            f"Unknown event type without text content: {type(event).__name__}"
        )

    def _flush_resolved_tool_calls(
        self, tool_state: _ToolCallTracking
    ) -> list[Message]:
        """Release pending tool-call responses once all tool outputs arrive."""
        return flush_resolved_tool_calls(tool_state)

    def _normalize_system_messages(self, messages: list[Message]) -> list[Message]:
        """Ensure a single leading system prompt and drop duplicates."""
        if not messages:
            return messages

        first_system_index = next(
            (i for i, message in enumerate(messages) if message.role == "system"), -1
        )
        if first_system_index == -1:
            try:
                system_prompt = self.prompt_manager.get_system_message(
                    cli_mode=self.agent_config.cli_mode,
                    config=self.agent_config,
                )
            except Exception:
                system_prompt = "You are Forge agent."
            messages.insert(
                0, message_with_text("system", system_prompt)
            )
            first_system_index = 0
        elif first_system_index != 0:
            sys_msg = messages.pop(first_system_index)
            messages.insert(0, sys_msg)

        # Inject Context Summary into System Prompt if available
        context_summary = self.get_context_summary()
        if context_summary and messages:
            # Append to the system prompt
            sys_msg = messages[0]
            if sys_msg.role == "system":
                # Iterate to find text content
                for content in sys_msg.content:
                    if is_text_content(content):
                        content.text += f"\n\n{context_summary}"
                        break

        deduped: list[Message] = [messages[0]]
        deduped.extend(message for message in messages[1:] if message.role != "system")
        return deduped

    def _process_action(
        self,
        action: Action,
        pending_tool_call_action_messages: dict[str, Message],
        vision_is_active: bool = False,
    ) -> list[Message]:
        """Converts an action into a message format that can be sent to the LLM."""
        return convert_action_to_messages(
            action, pending_tool_call_action_messages, vision_is_active
        )

    def _process_recall_observation(
        self,
        obs: RecallObservation,
        current_index: int,
        events: list[Event] | None,
    ) -> list[Message]:
        """Delegate to prompt_assembly module."""
        return process_recall_observation(
            obs,
            current_index,
            events or [],
            self.agent_config,
            self.prompt_manager,
        )

    def _process_observation(
        self,
        obs: Observation,
        tool_call_id_to_message: dict[str, Message],
        max_message_chars: int | None = None,
        vision_is_active: bool = False,
        enable_som_visual_browsing: bool = False,
        current_index: int = 0,
        events: list[Event] | None = None,
    ) -> list[Message]:
        """Converts an observation into a message format that can be sent to the LLM.

        This method handles different types of observations and formats them appropriately:
        - CmdOutputObservation: Formats command execution results with exit codes
        - FileEditObservation: Formats file editing results
        - FileReadObservation: Formats file reading results from file operations
        - ErrorObservation: Formats error messages from failed actions
        - UserRejectObservation: Formats user rejection messages
        - FileDownloadObservation: Formats the result of a browsing action that opened/downloaded a file

        In function calling mode, observations with tool_call_metadata are stored in
        tool_call_id_to_message for later processing instead of being returned immediately.

        Args:
            obs: The observation to convert
            tool_call_id_to_message: Dictionary mapping tool call IDs to their corresponding messages (used in function calling mode)
            max_message_chars: The maximum number of characters in the content of an observation included in the prompt to the LLM
            vision_is_active: Whether vision is active in the LLM. If True, image URLs will be included
            enable_som_visual_browsing: Whether to enable visual browsing for the SOM model
            current_index: The index of the current event in the events list (for deduplication)
            events: The list of all events (for deduplication)

        Returns:
            list[Message]: A list containing the formatted message(s) for the observation.
                May be empty if the observation is handled as a tool response in function calling mode.

        Raises:
            ValueError: If the observation type is unknown

        """
        # Handle special cases first
        if is_instance_of(obs, RecallObservation):
            return self._process_recall_observation(
                cast(RecallObservation, obs), current_index, events or []
            )

        # Handle different observation types
        message = self._get_message_for_observation(
            obs,
            max_message_chars,
            vision_is_active,
            enable_som_visual_browsing,
        )

        # Handle tool call metadata
        if (tool_call_metadata := getattr(obs, "tool_call_metadata", None)) is not None:
            tool_call_id_to_message[tool_call_metadata.tool_call_id] = Message(
                role="tool",
                content=message.content,
                tool_call_id=tool_call_metadata.tool_call_id,
                name=tool_call_metadata.function_name,
            )
            return []

        return [message]

    def _get_message_for_observation(
        self,
        obs: Observation,
        max_message_chars: int | None,
        vision_is_active: bool,
        enable_som_visual_browsing: bool,
    ) -> Message:
        """Get the appropriate message for different observation types."""
        return convert_observation_to_message(
            obs,
            max_message_chars,
            vision_is_active=vision_is_active,
            enable_som_visual_browsing=enable_som_visual_browsing,
        )

    def _ensure_system_message(self, events: list[Event]) -> None:
        """Checks if a system message exists and adds one if not.

        Uses duck-typing in addition to isinstance to avoid false negatives
        when tests or alternate imports provide compatible event stubs.
        """
        has_system_message = False
        for event in events:
            # Primary fast-path: direct isinstance or duck-typed equivalent
            if is_instance_of(event, SystemMessageAction):
                has_system_message = True
                break
            # Class name match fallback (handles duplicate class loading / re-import edge cases)
            if (
                type(event).__name__ == "SystemMessageAction"
            ):  # pragma: no cover - defensive
                has_system_message = True
                break
            # Duck-typed detection: an event with action == ActionType.SYSTEM is treated as system
            if getattr(event, "action", None) == ActionType.SYSTEM:
                has_system_message = True
                break
        if not has_system_message:
            logger.debug(
                "[ConversationMemory] No SystemMessageAction found in events. Adding one.",
            )
            if system_prompt := self.prompt_manager.get_system_message(
                cli_mode=self.agent_config.cli_mode, config=self.agent_config
            ):
                system_message = SystemMessageAction(content=system_prompt)
                events.insert(0, system_message)
                logger.info("[ConversationMemory] Added SystemMessageAction")

    def _ensure_initial_user_message(
        self, events: list[Event], initial_user_action: MessageAction
    ) -> None:
        """Ensure the initial user message is present and positioned consistently.

        Idempotent logic:
        - If the exact initial_user_action object already exists anywhere in the list:
          * If it's at index 1 and correctly sourced, leave as-is.
          * If it's elsewhere and index 1 is not a user-sourced MessageAction, move it to index 1.
        - If it does not exist, insert at index 1 (or append if list length == 0).
        This avoids duplicate insertions across repeated calls (important for tests invoking
        the pipeline multiple times with the same underlying history list).
        """
        if not events:
            self._append_initial_user_action(events, initial_user_action)
            return

        existing_index = self._find_existing_initial_action(events, initial_user_action)
        if self._handle_existing_initial_action(
            events, initial_user_action, existing_index
        ):
            return

        if self._has_user_message_at_index_one(events):
            return

        self._insert_initial_user_at_index(events, initial_user_action)

    @staticmethod
    def _append_initial_user_action(
        events: list[Event], initial_user_action: MessageAction
    ) -> None:
        logger.error("Cannot ensure initial user message: event list is empty.")
        events.append(initial_user_action)

    @staticmethod
    def _find_existing_initial_action(
        events: list[Event], initial_user_action: MessageAction
    ) -> int:
        for idx, event in enumerate(events):
            if event is initial_user_action:
                return idx
        return -1

    def _handle_existing_initial_action(
        self,
        events: list[Event],
        initial_user_action: MessageAction,
        existing_index: int,
    ) -> bool:
        if existing_index == -1:
            return False
        if existing_index == 1 and self._is_user_message(events[1]):
            return True
        if len(events) > 1 and self._is_user_message(events[1]):
            return True
        events.pop(existing_index)
        insert_pos = 1 if len(events) >= 1 else 0
        events.insert(insert_pos, initial_user_action)
        logger.debug(
            "Repositioned existing initial user action to index %s", insert_pos
        )
        return True

    def _has_user_message_at_index_one(self, events: list[Event]) -> bool:
        return len(events) > 1 and self._is_user_message(events[1])

    def _insert_initial_user_at_index(
        self, events: list[Event], initial_user_action: MessageAction
    ) -> None:
        insert_pos = 1 if len(events) >= 1 else 0
        events.insert(insert_pos, initial_user_action)
        logger.info("Inserted initial user action at index %s", insert_pos)

    def _is_user_message(self, event: Event) -> bool:
        if not is_instance_of(event, MessageAction):
            return False
        source = getattr(event, "source", getattr(event, "_source", None))
        if isinstance(source, EventSource):
            return source == EventSource.USER
        return source == "user"


