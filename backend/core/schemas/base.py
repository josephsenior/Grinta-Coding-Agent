"""Base Pydantic schemas for App events with versioning support."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from backend.core.enums import EventSource, EventVersion


class EventMetadata(BaseModel):
    """Metadata attached to all events."""

    event_id: int | None = Field(None, description='Unique event identifier')
    sequence: int | None = Field(None, description='Event sequence number for ordering')
    timestamp: datetime | None = Field(
        None, description='Event timestamp in ISO format'
    )
    source: EventSource | None = Field(
        None, description='Event source (AGENT, USER, ENVIRONMENT)'
    )
    cause: int | None = Field(None, description='ID of event that caused this event')
    hidden: bool = Field(False, description='Whether this event is hidden from the UI')
    timeout: float | None = Field(None, description='Timeout value in seconds')
    response_id: str | None = Field(None, description='LLM response ID for this event')
    trace_id: str | None = Field(None, description='Distributed tracing ID')

    model_config = ConfigDict(
        use_enum_values=True,
    )

    @field_serializer('timestamp')
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


def _create_default_event_metadata() -> EventMetadata:
    """Factory used to provide default metadata instances for events."""
    return EventMetadata.model_construct()


class BaseEventSchema(BaseModel):
    """Base schema for all App events with versioning support."""

    schema_version: EventVersion = Field(
        EventVersion.V1, description='Schema version for this event'
    )
    metadata: EventMetadata = Field(
        default_factory=_create_default_event_metadata, description='Event metadata'
    )

    model_config = ConfigDict(
        use_enum_values=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary."""
        return self.model_dump(mode='json', exclude_none=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseEventSchema:
        """Deserialize event from dictionary."""
        return cls.model_validate(data)


class EventSchemaV1(BaseEventSchema):
    """Version 1.0.0 of the event schema.

    This is the current production schema version.
    """

    schema_version: EventVersion = Field(EventVersion.V1, frozen=True)

    @field_validator('schema_version', mode='before')
    @classmethod
    def validate_version(cls, v: Any) -> EventVersion:
        """Ensure schema version is V1."""
        if isinstance(v, str):
            return EventVersion(v)
        return EventVersion.V1
