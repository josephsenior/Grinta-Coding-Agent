"""Protocol interfaces for orchestrator subsystem components.

These Protocols define the contracts that planner, executor, safety,
and memory managers must satisfy.  The ``Orchestrator`` depends only
on these structural types, making it straightforward to swap
implementations or build test doubles without subclassing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from backend.core.contracts.state import State
    from backend.core.message import Message
    from backend.ledger.action import Action, MessageAction
    from backend.ledger.event import Event
    from backend.ledger.stream import EventStream


# Re-usable type alias for LLM tool definitions (OpenAI-compatible dict).
# Using ``TypedDict`` gives downstream code basic structural guarantees
# without requiring full OpenAI-SDK models.
class ChatCompletionToolParam(TypedDict, total=False):
    """OpenAI-compatible tool definition for function calling."""

    type: str  # e.g. "function"
    function: dict[str, Any]  # name, description, parameters, strict …


# ------------------------------------------------------------------ #
# Planner
# ------------------------------------------------------------------ #
@runtime_checkable
class PlannerProtocol(Protocol):
    """Assembles tool definitions and LLM request parameters."""

    def build_toolset(self) -> list[ChatCompletionToolParam]:
        """Return the full set of tool definitions available for this turn."""
        raise NotImplementedError

    def build_llm_params(
        self,
        messages: list[dict[str, Any]],
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict[str, Any]:
        """Construct the keyword arguments dict to pass to the LLM."""
        raise NotImplementedError


# ------------------------------------------------------------------ #
# Executor
# ------------------------------------------------------------------ #
@runtime_checkable
class ExecutionResultProtocol(Protocol):
    """Container for executor outcomes."""

    actions: list[Action]
    response: Any
    execution_time: float
    error: str | None


@runtime_checkable
class ExecutorProtocol(Protocol):
    """Drives a single LLM turn and converts the response to actions."""

    def execute(
        self,
        params: dict[str, Any],
        event_stream: EventStream | None,
    ) -> ExecutionResultProtocol:
        """Stream or invoke the LLM and return parsed actions."""
        raise NotImplementedError

    async def async_execute(
        self,
        params: dict[str, Any],
        event_stream: EventStream | None,
    ) -> ExecutionResultProtocol:
        """Async: invoke the LLM and return parsed actions."""
        raise NotImplementedError


# ------------------------------------------------------------------ #
# Safety manager
# ------------------------------------------------------------------ #
@runtime_checkable
class SafetyManagerProtocol(Protocol):
    """Pre- and post-action safety validation pipeline."""

    def should_enforce_tools(
        self,
        last_user_message: str | None,
        state: State,
        default: str,
    ) -> str:
        """Decide whether to force tool-use for the current turn."""
        raise NotImplementedError

    def apply(
        self,
        response_text: str,
        actions: list[Action],
    ) -> tuple[bool, list[Action]]:
        """Run the full safety pipeline; returns (continue, updated_actions)."""
        raise NotImplementedError


# ------------------------------------------------------------------ #
# Memory manager
# ------------------------------------------------------------------ #
class CondensedHistoryResult(Protocol):
    """Structural type for condensed history returned by memory managers."""

    events: list[Event]
    pending_action: Action | None


@runtime_checkable
class MemoryManagerProtocol(Protocol):
    """History condensation and LLM message construction."""

    def condense_history(self, state: State) -> CondensedHistoryResult:
        """Return condensed events and an optional pending action."""
        ...

    def get_initial_user_message(
        self,
        events: list[Event],
    ) -> MessageAction:
        """Locate the first user message from the event history."""
        ...

    def build_messages(
        self,
        condensed_history: list[Event],
        initial_user_message: MessageAction,
        llm_config: Any,
    ) -> list[Message]:
        """Convert condensed events into an LLM-ready message list."""
        ...
