"""Agent-focused action types emitted in Forge event streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ActionType, AgentState
from backend.events.action.action import Action
from backend.core.enums import RecallType


@dataclass
class ChangeAgentStateAction(Action):
    """Fake action, just to notify the client that a task state has changed."""

    agent_state: AgentState | str = ""
    thought: str = ""
    action: ClassVar[str] = ActionType.CHANGE_AGENT_STATE

    @property
    def message(self) -> str:
        """Get human-readable message for state change."""
        return f"Agent state changed to {self.agent_state}"

    __test__ = False


@dataclass
class PlaybookFinishAction(Action):
    """An action where the agent finishes the task.

    Attributes:
        final_thought (str): The message to send to the user.
        outputs (dict): The other outputs of the agent, for instance "content".
        thought (str): The agent's explanation of its actions.
        action (str): The action type, namely ActionType.FINISH.

    """

    final_thought: str = ""
    outputs: dict[str, Any] = field(default_factory=dict)
    thought: str = ""
    force_finish: bool = False
    action: ClassVar[str] = ActionType.FINISH

    @property
    def message(self) -> str:
        """Get completion message for user."""
        if self.thought != "":
            return self.thought
        return "All done! What's next on the agenda?"

    __test__ = False


@dataclass
class AgentThinkAction(Action):
    """An action where the agent logs a thought.

    Attributes:
        thought (str): The agent's explanation of its actions.
        action (str): The action type, namely ActionType.THINK.

    """

    thought: str = ""
    action: ClassVar[str] = ActionType.THINK

    @property
    def message(self) -> str:
        """Get formatted thinking message."""
        return f"I am thinking...: {self.thought}"

    __test__ = False


@dataclass
class AgentRejectAction(Action):
    """An action where the agent rejects the task."""

    outputs: dict[str, Any] = field(default_factory=dict)
    thought: str = ""
    action: ClassVar[str] = ActionType.REJECT

    @property
    def message(self) -> str:
        """Get rejection message with optional reason."""
        msg: str = "Task is rejected by the agent."
        if "reason" in self.outputs:
            msg += " Reason: " + self.outputs["reason"]
        return msg

    __test__ = False


@dataclass
class RecallAction(Action):
    """This action is used for retrieving content, e.g., from the global directory or user workspace."""

    recall_type: RecallType = RecallType.WORKSPACE_CONTEXT
    query: str = ""
    thought: str = ""
    action: ClassVar[str] = ActionType.RECALL

    @property
    def message(self) -> str:
        """Get recall query message."""
        return f"Retrieving content for: {self.query[:50]}"

    def __str__(self) -> str:
        """Return a concise representation showing the recall query."""
        ret = "**RecallAction**\n"
        ret += f"QUERY: {self.query[:50]}"
        return ret

    __test__ = False


@dataclass
class CondensationAction(Action):
    """This action indicates a condensation of the conversation history is happening.

    There are two ways to specify the events to be forgotten:
    1. By providing a list of event IDs.
    2. By providing the start and end IDs of a range of events.

    In the second case, we assume that event IDs are monotonically increasing, and that _all_ events between the start and end IDs are to be forgotten.

    Raises:
        ValueError: If the optional fields are not instantiated in a valid configuration.

    """

    action: ClassVar[str] = ActionType.CONDENSATION
    forgotten_event_ids: list[int] | None = None
    "The IDs of the events that are being forgotten (removed from the `View` given to the LLM)."
    forgotten_events_start_id: int | None = None
    "The ID of the first event to be forgotten in a range of events."
    forgotten_events_end_id: int | None = None
    "The ID of the last event to be forgotten in a range of events."
    summary: str | None = None
    "An optional summary of the events being forgotten."
    summary_offset: int | None = None
    "An optional offset to the start of the resulting view indicating where the summary should be inserted."

    def _validate_field_polymorphism(self) -> bool:
        """Check if the optional fields are instantiated in a valid configuration."""
        using_event_ids = self.forgotten_event_ids is not None
        using_event_range = (
            self.forgotten_events_start_id is not None
            and self.forgotten_events_end_id is not None
        )
        forgotten_event_configuration = using_event_ids ^ using_event_range
        summary_configuration = (
            self.summary is None and self.summary_offset is None
        ) or (self.summary is not None and self.summary_offset is not None)
        return forgotten_event_configuration and summary_configuration

    def __post_init__(self):
        """Validate that the provided fields describe exactly one forgetting strategy."""
        if not self._validate_field_polymorphism():
            msg = "Invalid configuration of the optional fields."
            raise ValueError(msg)

    @property
    def forgotten(self) -> list[int]:
        """The list of event IDs that should be forgotten."""
        if not self._validate_field_polymorphism():
            msg = "Invalid configuration of the optional fields."
            raise ValueError(msg)
        if self.forgotten_event_ids is not None:
            return self.forgotten_event_ids
        assert self.forgotten_events_start_id is not None
        assert self.forgotten_events_end_id is not None
        return list(
            range(self.forgotten_events_start_id, self.forgotten_events_end_id + 1)
        )

    @property
    def message(self) -> str:
        """Get condensation summary or event list message."""
        if self.summary:
            return f"Summary: {self.summary}"
        return f"Condenser is dropping the events: {self.forgotten}."


@dataclass
class CondensationRequestAction(Action):
    """This action is used to request a condensation of the conversation history.

    Attributes:
        action (str): The action type, namely ActionType.CONDENSATION_REQUEST.

    """

    action: ClassVar[str] = ActionType.CONDENSATION_REQUEST

    @property
    def message(self) -> str:
        """Get condensation request message."""
        return "Requesting a condensation of the conversation history."


@dataclass
class TaskTrackingAction(Action):
    """An action where the agent writes or updates a task list for task management.

    Attributes:
        task_list (list): The list of task items with their status and metadata.
        thought (str): The agent's explanation of its actions.
        action (str): The action type, namely ActionType.TASK_TRACKING.

    """

    command: str = "view"
    task_list: list[dict[str, Any]] = field(default_factory=list)
    thought: str = ""
    action: ClassVar[str] = ActionType.TASK_TRACKING

    @property
    def message(self) -> str:
        """Get task tracking message with count."""
        num_tasks = len(self.task_list)
        if num_tasks == 0:
            return "Clearing the task list."
        if num_tasks == 1:
            return "Managing 1 task item."
        return f"Managing {num_tasks} task items."
