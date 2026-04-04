"""Pydantic schemas for all App observation types."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from backend.core.schemas.base import EventSchemaV1
from backend.core.schemas.enums import ObservationType
from backend.core.schemas.metadata import CmdOutputMetadataSchema


class ObservationSchemaV1(EventSchemaV1):
    """Base schema for all observation types."""

    observation_type: str = Field(..., min_length=1, description='Type of observation')
    content: str = Field(..., description='Observation content')

    @field_validator('observation_type')
    @classmethod
    def validate_observation_type(cls, v: str) -> str:
        """Validate observation type is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='observation_type')


class CmdOutputObservationSchema(ObservationSchemaV1):
    """Schema for CmdOutputObservation."""

    observation_type: Literal['run'] = Field(ObservationType.RUN.value, frozen=True)
    command: str = Field(..., min_length=1, description='Command that was executed')
    content: str = Field(..., description='Command output')
    cmd_metadata: CmdOutputMetadataSchema | None = Field(
        default=None, description='Command metadata'
    )
    hidden: bool = Field(default=False, description='Whether observation is hidden')

    @field_validator('command')
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Validate command is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='command')


class FileReadObservationSchema(ObservationSchemaV1):
    """Schema for FileReadObservation."""

    observation_type: Literal['read'] = Field(ObservationType.READ.value, frozen=True)
    path: str = Field(..., min_length=1, description='Path to file that was read')
    content: str = Field(..., description='File content')

    @field_validator('path')
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate path is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='path')


class FileEditObservationSchema(ObservationSchemaV1):
    """Schema for FileEditObservation."""

    observation_type: Literal['edit'] = Field(ObservationType.EDIT.value, frozen=True)
    path: str = Field(..., min_length=1, description='Path to file that was edited')
    content: str = Field(..., description='Edit result content')

    @field_validator('path')
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate path is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='path')


class ErrorObservationSchema(ObservationSchemaV1):
    """Schema for ErrorObservation."""

    observation_type: Literal['error'] = Field(ObservationType.ERROR.value, frozen=True)
    content: str = Field(..., min_length=1, description='Error message')
    error_id: str | None = Field(default=None, description='Error identifier')

    @field_validator('content')
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='content')


class MessageObservationSchema(ObservationSchemaV1):
    """Schema for MessageObservation."""

    observation_type: Literal['message'] = Field(
        ObservationType.MESSAGE.value, frozen=True
    )
    content: str = Field(..., min_length=1, description='Message content')

    @field_validator('content')
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content is non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='content')


class TerminalObservationSchema(ObservationSchemaV1):
    """Schema for TerminalObservation."""

    observation_type: Literal['terminal'] = Field(
        ObservationType.TERMINAL.value, frozen=True
    )
    session_id: str = Field(..., min_length=1, description='Terminal session ID')
    content: str = Field(..., description='Terminal output buffer')


# Union type for all observation schemas
ObservationSchemaUnion = (
    CmdOutputObservationSchema
    | FileReadObservationSchema
    | FileEditObservationSchema
    | ErrorObservationSchema
    | MessageObservationSchema
    | TerminalObservationSchema
)
