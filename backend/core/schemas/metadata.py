"""Pydantic schemas for event metadata."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.constants import DEFAULT_CMD_EXIT_CODE, DEFAULT_CMD_PID


class CmdOutputMetadataSchema(BaseModel):
    """Schema for command output metadata captured from PS1."""

    exit_code: int = Field(
        default=DEFAULT_CMD_EXIT_CODE, description='Command exit code (-1 if unknown)'
    )
    pid: int = Field(
        default=DEFAULT_CMD_PID, ge=-1, description='Process ID (-1 if unknown)'
    )
    username: str | None = Field(
        default=None, description='Username who executed the command'
    )
    hostname: str | None = Field(
        default=None, description='Hostname where the command was executed'
    )
    working_dir: str | None = Field(
        default=None, description='Working directory where the command was executed'
    )
    py_interpreter_path: str | None = Field(
        default=None, description='Path to the Python interpreter (if available)'
    )
    prefix: str = Field(
        default='', description='Prefix text to prepend to command output'
    )
    suffix: str = Field(
        default='', description='Suffix text to append to command output'
    )

    @field_validator('username', 'hostname', 'working_dir', 'py_interpreter_path')
    @classmethod
    def validate_optional_strings(cls, v: str | None) -> str | None:
        """Validate optional string fields are non-empty if provided."""
        if v is not None:
            from backend.core.type_safety.type_safety import validate_non_empty_string

            return validate_non_empty_string(v, name='field')
        return v


class ToolCallMetadataSchema(BaseModel):
    """Schema for LLM tool/function call metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    function_name: str = Field(
        ..., min_length=1, description='Name of the function called'
    )
    tool_call_id: str = Field(
        ..., min_length=1, description='Unique ID for this tool call'
    )
    model_response: dict[str, Any] | None = Field(
        default=None,
        description='Complete LLM response containing the tool call (lightweight representation)',
    )
    total_calls_in_response: int = Field(
        ..., ge=1, description='Number of tool calls in the response'
    )

    @field_validator('function_name', 'tool_call_id')
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')
