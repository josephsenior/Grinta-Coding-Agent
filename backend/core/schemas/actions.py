"""Pydantic schemas for all Forge action types."""

from __future__ import annotations

from typing import Literal, Union

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
        default=None, description="String to replace (str_replace command)"
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


# Union type for all action schemas
ActionSchemaUnion = Union[
    FileReadActionSchema,
    FileWriteActionSchema,
    FileEditActionSchema,
    CmdRunActionSchema,
    MessageActionSchema,
    SystemMessageActionSchema,
    PlaybookFinishActionSchema,
    AgentRejectActionSchema,
    ChangeAgentStateActionSchema,
    NullActionSchema,
]
