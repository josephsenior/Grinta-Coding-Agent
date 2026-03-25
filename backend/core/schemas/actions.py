"""Pydantic schemas for all Forge action types."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import Field, field_validator

from backend.core.schemas.base import EventSchemaV1
from backend.core.schemas.enums import ActionType


class ActionSchemaV1(EventSchemaV1):
    """Base schema for all action types."""

    action_type: str = Field(..., min_length=1, description="Type of action")
    runnable: bool = Field(default=False, description="Whether action can be executed")
    confirmation_state: str | None = Field(
        default=None, description="Action confirmation status"
    )
    security_risk: int | None = Field(
        default=None, ge=0, description="Security risk level for this action"
    )
    thought: str | None = Field(
        default=None, description="Agent's reasoning for this action"
    )

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, v: str) -> str:
        """Validate action type is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="action_type")


class FileReadActionSchema(ActionSchemaV1):
    """Schema for FileReadAction."""

    action_type: Literal["read"] = Field(ActionType.READ.value, frozen=True)
    runnable: bool = Field(True, frozen=True)
    path: str = Field(..., min_length=1, description="Path to file to read")
    start: int = Field(default=0, ge=0, description="Starting line number (0-indexed)")
    end: int = Field(default=-1, description="Ending line number (-1 for end of file)")
    impl_source: str | None = Field(default=None, description="Implementation source")
    view_range: list[int] | None = Field(
        default=None, description="View range for file reading"
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate path is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="path")


class FileWriteActionSchema(ActionSchemaV1):
    """Schema for FileWriteAction."""

    action_type: Literal["write"] = Field(ActionType.WRITE.value, frozen=True)
    runnable: bool = Field(True, frozen=True)
    path: str = Field(..., min_length=1, description="Path to file to write")
    content: str = Field(..., description="Content to write to file")
    start: int = Field(default=0, ge=0, description="Starting line number (0-indexed)")
    end: int = Field(default=-1, description="Ending line number (-1 for end of file)")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate path is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="path")


class FileEditActionSchema(ActionSchemaV1):
    """Schema for FileEditAction."""

    action_type: Literal["edit"] = Field(ActionType.EDIT.value, frozen=True)
    runnable: bool = Field(True, frozen=True)
    path: str = Field(..., min_length=1, description="Path to file to edit")
    command: str | None = Field(
        default=None, description="Editing command (FILE_EDITOR mode)"
    )
    file_text: str | None = Field(
        default=None, description="File content for create command"
    )
    old_str: str | None = Field(
        default=None, description="String to replace (replace_text command)"
    )
    new_str: str | None = Field(default=None, description="Replacement string")
    insert_line: int | None = Field(
        default=None, ge=1, description="Line number for insert command"
    )
    content: str | None = Field(
        default=None, description="Content to write (LLM-based editing)"
    )
    start: int = Field(default=1, ge=1, description="Starting line number (1-indexed)")
    end: int = Field(default=-1, description="Ending line number (-1 for end of file)")
    impl_source: str | None = Field(
        default=None,
        description="Implementation source (LLM_BASED_EDIT or FILE_EDITOR)",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate path is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="path")


class CmdRunActionSchema(ActionSchemaV1):
    """Schema for CmdRunAction."""

    action_type: Literal["run"] = Field(ActionType.RUN.value, frozen=True)
    runnable: bool = Field(True, frozen=True)
    command: str = Field(..., min_length=1, description="Shell command to execute")
    is_input: bool = Field(
        default=False, description="Whether command is user input (for stdin)"
    )
    blocking: bool = Field(
        default=False, description="Whether to wait for command to complete"
    )
    is_static: bool = Field(
        default=False, description="Whether command is static (from static analysis)"
    )
    cwd: str | None = Field(default=None, description="Working directory for command")
    hidden: bool = Field(default=False, description="Whether to hide command from user")

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Validate command is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="command")


class MessageActionSchema(ActionSchemaV1):
    """Schema for MessageAction."""

    action_type: Literal["message"] = Field(ActionType.MESSAGE.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    content: str = Field(..., min_length=1, description="Message content")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="content")


class SystemMessageActionSchema(ActionSchemaV1):
    """Schema for SystemMessageAction."""

    action_type: Literal["system"] = Field(ActionType.SYSTEM.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    content: str = Field(..., min_length=1, description="System message content")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="content")


class PlaybookFinishActionSchema(ActionSchemaV1):
    """Schema for PlaybookFinishAction."""

    action_type: Literal["finish"] = Field(ActionType.FINISH.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    message: str | None = Field(None, description="Finish message")


class AgentRejectActionSchema(ActionSchemaV1):
    """Schema for AgentRejectAction."""

    action_type: Literal["reject"] = Field(ActionType.REJECT.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    message: str | None = Field(None, description="Rejection message")


class ChangeAgentStateActionSchema(ActionSchemaV1):
    """Schema for ChangeAgentStateAction."""

    action_type: Literal["change_agent_state"] = Field(
        ActionType.CHANGE_AGENT_STATE.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)
    state: str = Field(..., min_length=1, description="New agent state")

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Validate state is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="state")


class NullActionSchema(ActionSchemaV1):
    """Schema for NullAction."""

    action_type: Literal["null"] = Field(ActionType.NULL.value, frozen=True)
    runnable: bool = Field(False, frozen=True)


class TerminalRunActionSchema(ActionSchemaV1):
    """Schema for TerminalRunAction."""

    action_type: Literal["terminal_run"] = Field(
        ActionType.TERMINAL_RUN.value, frozen=True
    )
    runnable: bool = Field(True, frozen=True)
    command: str = Field(..., min_length=1, description="Command to start session")
    cwd: str | None = Field(default=None, description="Working directory")


class TerminalInputActionSchema(ActionSchemaV1):
    """Schema for TerminalInputAction."""

    action_type: Literal["terminal_input"] = Field(
        ActionType.TERMINAL_INPUT.value, frozen=True
    )
    runnable: bool = Field(True, frozen=True)
    session_id: str = Field(..., min_length=1, description="Terminal session ID")
    input: str = Field(..., description="Input string")
    is_control: bool = Field(default=False, description="Is control char (C-c, etc.)")


class TerminalReadActionSchema(ActionSchemaV1):
    """Schema for TerminalReadAction."""

    action_type: Literal["terminal_read"] = Field(
        ActionType.TERMINAL_READ.value, frozen=True
    )
    runnable: bool = Field(True, frozen=True)
    session_id: str = Field(..., min_length=1, description="Terminal session ID")


class BrowseInteractiveActionSchema(ActionSchemaV1):
    """Schema for BrowseInteractiveAction.

    Action to perform interactive browser operations.
    This is a higher-level browsing action that can encode one or more
    browser interactions (clicks, typing, navigation) for an external
    browser tool/runtime.
    """

    action_type: Literal["browse_interactive"] = Field(
        ActionType.BROWSE_INTERACTIVE.value, frozen=True
    )
    runnable: bool = Field(True, frozen=True)
    browser_actions: str = Field(
        default="", description="Browser actions to execute (clicks, typing, navigation)"
    )


class AgentThinkActionSchema(ActionSchemaV1):
    """Schema for AgentThinkAction.

    An action where the agent logs a thought.
    """

    action_type: Literal["think"] = Field(ActionType.THINK.value, frozen=True)
    runnable: bool = Field(False, frozen=True)


class ClarificationRequestActionSchema(ActionSchemaV1):
    """Schema for ClarificationRequestAction.

    An action where the agent asks for clarification before proceeding.
    This enables the LLM to proactively request clarification rather than
    making assumptions that may lead to errors.
    """

    action_type: Literal["clarification"] = Field(
        ActionType.CLARIFICATION.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)
    question: str = Field(..., description="The clarification question")
    options: list[str] = Field(
        default_factory=list, description="Optional multiple choice options"
    )
    context: str = Field(default="", description="Why clarification is needed")


class EscalateToHumanActionSchema(ActionSchemaV1):
    """Schema for EscalateToHumanAction.

    An action where the agent requests escalation to human assistance.
    This enables the LLM to explicitly request help when it's stuck,
    has tried multiple approaches without success, or needs human intervention.
    """

    action_type: Literal["escalate"] = Field(ActionType.ESCALATE.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    reason: str = Field(..., description="Why escalation is being requested")
    attempts_made: list[str] = Field(
        default_factory=list, description="Summary of approaches already tried"
    )
    specific_help_needed: str = Field(
        default="", description="What kind of help is needed"
    )


class MCPActionSchema(ActionSchemaV1):
    """Schema for MCPAction.

    Action to call an MCP (Model Context Protocol) tool.
    """

    action_type: Literal["call_tool_mcp"] = Field(ActionType.MCP.value, frozen=True)
    runnable: bool = Field(True, frozen=True)
    name: str = Field(..., description="Name of the MCP tool to call")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments to pass to the tool"
    )


class ProposalActionSchema(ActionSchemaV1):
    """Schema for ProposalAction.

    An action where the agent proposes options before committing to a path.
    This enables the LLM to suggest different approaches and get user feedback
    before executing potentially risky or irreversible actions.
    """

    action_type: Literal["proposal"] = Field(ActionType.PROPOSAL.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    options: list[dict[str, Any]] = Field(
        default_factory=list, description="List of proposed options"
    )
    recommended: int = Field(default=0, description="Index of the recommended option")
    rationale: str = Field(
        default="", description="Why these options are being proposed"
    )


class RecallActionSchema(ActionSchemaV1):
    """Schema for RecallAction.

    This action is used for retrieving content, e.g., from the global directory or user workspace.
    """

    action_type: Literal["recall"] = Field(ActionType.RECALL.value, frozen=True)
    runnable: bool = Field(False, frozen=True)
    recall_type: str = Field(default="workspace_context", description="Type of recall")
    query: str = Field(..., description="Recall query")


class StreamingChunkActionSchema(ActionSchemaV1):
    """Schema for StreamingChunkAction.

    Streaming chunk from LLM for real-time token display.
    Emitted during LLM streaming to show tokens as they arrive,
    providing instant feedback.
    """

    action_type: Literal["streaming_chunk"] = Field(
        ActionType.STREAMING_CHUNK.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)
    chunk: str = Field(..., description="The new token/chunk text")
    accumulated: str = Field(default="", description="All text accumulated so far")
    is_final: bool = Field(default=False, description="True when streaming is complete")


class TaskTrackingActionSchema(ActionSchemaV1):
    """Schema for TaskTrackingAction.

    An action where the agent writes or updates a task list for task management.
    """

    action_type: Literal["task_tracking"] = Field(
        ActionType.TASK_TRACKING.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)
    command: str = Field(default="view", description="Task tracking command")
    task_list: list[dict[str, Any]] = Field(
        default_factory=list, description="List of task items"
    )


class UncertaintyActionSchema(ActionSchemaV1):
    """Schema for UncertaintyAction.

    An action where the agent expresses uncertainty about its current understanding or observations.
    This enables the LLM to explicitly flag doubt rather than guessing or hallucinating.
    The system can then provide clarification, additional context, or switch strategy.
    """

    action_type: Literal["uncertainty"] = Field(
        ActionType.UNCERTAINTY.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)
    uncertainty_level: float = Field(default=0.5, description="Confidence level 0.0-1.0")
    specific_concerns: list[str] = Field(
        default_factory=list, description="Specific things the agent is uncertain about"
    )
    requested_information: str = Field(
        default="", description="What information would help resolve uncertainty"
    )


class DelegateTaskActionSchema(ActionSchemaV1):
    """Schema for DelegateTaskAction.

    An action where the orchestrator delegates a subtask to a worker agent.
    """

    action_type: Literal["delegate_task"] = Field(
        ActionType.DELEGATE_TASK.value, frozen=True
    )
    runnable: bool = Field(True, frozen=True)
    task_description: str = Field(
        default="", description="Description of the delegated task"
    )
    files: list[str] = Field(
        default_factory=list, description="Relevant files for the task"
    )
    parallel_tasks: list[dict[str, Any]] = Field(
        default_factory=list, description="Parallel tasks to spawn"
    )


class CondensationActionSchema(ActionSchemaV1):
    """Schema for CondensationAction.

    This action indicates a condensation of the conversation history is happening.
    There are two ways to specify the events to be forgotten:
    1. By providing a list of event IDs.
    2. By providing the start and end IDs of a range of events.
    In the second case, we assume that event IDs are monotonically increasing, and that _all_ events between the start and end IDs are to be forgotten.
    """

    action_type: Literal["condensation"] = Field(
        ActionType.CONDENSATION.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)
    forgotten_event_ids: list[int] | None = Field(
        default=None, description="List of event IDs to forget"
    )
    forgotten_events_start_id: int | None = Field(
        default=None, description="Start ID of range to forget"
    )
    forgotten_events_end_id: int | None = Field(
        default=None, description="End ID of range to forget"
    )
    summary: str | None = Field(
        default=None, description="Summary of forgotten events"
    )
    summary_offset: int | None = Field(
        default=None, description="Offset for summary insertion"
    )


class CondensationRequestActionSchema(ActionSchemaV1):
    """Schema for CondensationRequestAction.

    This action is used to request a condensation of the conversation history.
    """

    action_type: Literal["condensation_request"] = Field(
        ActionType.CONDENSATION_REQUEST.value, frozen=True
    )
    runnable: bool = Field(False, frozen=True)


# Union type for all action schemas
ActionSchemaUnion = Union[
    FileReadActionSchema,
    FileWriteActionSchema,
    FileEditActionSchema,
    CmdRunActionSchema,
    MessageActionSchema,
    SystemMessageActionSchema,
    BrowseInteractiveActionSchema,
    PlaybookFinishActionSchema,
    AgentRejectActionSchema,
    ChangeAgentStateActionSchema,
    NullActionSchema,
    TerminalRunActionSchema,
    TerminalInputActionSchema,
    TerminalReadActionSchema,
    AgentThinkActionSchema,
    ClarificationRequestActionSchema,
    EscalateToHumanActionSchema,
    MCPActionSchema,
    ProposalActionSchema,
    RecallActionSchema,
    StreamingChunkActionSchema,
    TaskTrackingActionSchema,
    UncertaintyActionSchema,
    DelegateTaskActionSchema,
    CondensationActionSchema,
    CondensationRequestActionSchema,
]
