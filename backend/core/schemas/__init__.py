"""Formal Pydantic schemas for Forge events, actions, and observations.

This module provides versioned, type-safe schemas for all event types,
enabling explicit contracts, versioning, testing, and multi-agent expansion.
"""

from backend.core.schemas.actions import (
    ActionSchemaUnion,
    ActionSchemaV1,
    AgentRejectActionSchema,
    BrowseInteractiveActionSchema,
    ChangeAgentStateActionSchema,
    CmdRunActionSchema,
    FileEditActionSchema,
    FileReadActionSchema,
    FileWriteActionSchema,
    MessageActionSchema,
    NullActionSchema,
    PlaybookFinishActionSchema,
    SystemMessageActionSchema,
)
from backend.core.schemas.base import (
    BaseEventSchema,
    EventMetadata,
    EventSchemaV1,
    EventVersion,
)
from backend.core.schemas.enums import (
    ActionConfirmationStatus,
    ActionSecurityRisk,
    ActionType,
    AgentState,
    AppMode,
    EventSource,
    ExitReason,
    FileEditSource,
    FileReadSource,
    ObservationType,
    RecallType,
    RuntimeStatus,
)
from backend.core.schemas.observations import (
    CmdOutputObservationSchema,
    ErrorObservationSchema,
    FileEditObservationSchema,
    FileReadObservationSchema,
    MessageObservationSchema,
    ObservationSchemaUnion,
    ObservationSchemaV1,
)
from backend.core.schemas.retry import RetryConfig, RetryStrategy
from backend.core.schemas.serialization import (
    deserialize_event,
    migrate_schema_version,
    serialize_event,
    validate_event_schema,
)

__all__ = [
    # Base schemas
    "BaseEventSchema",
    "EventMetadata",
    "EventSchemaV1",
    "EventVersion",
    # Action schemas
    "ActionSchemaV1",
    "ActionType",
    "FileEditActionSchema",
    "FileReadActionSchema",
    "FileWriteActionSchema",
    "CmdRunActionSchema",
    "MessageActionSchema",
    "SystemMessageActionSchema",
    "BrowseInteractiveActionSchema",
    "PlaybookFinishActionSchema",
    "AgentRejectActionSchema",
    "ChangeAgentStateActionSchema",
    "NullActionSchema",
    "ActionSchemaUnion",
    # Observation schemas
    "ObservationSchemaV1",
    "CmdOutputObservationSchema",
    "ObservationType",
    "FileReadObservationSchema",
    "FileEditObservationSchema",
    "ErrorObservationSchema",
    "MessageObservationSchema",
    "ObservationSchemaUnion",
    # Serialization
    "serialize_event",
    "deserialize_event",
    "migrate_schema_version",
    "validate_event_schema",
    # Agent lifecycle
    "AgentState",
    "AppMode",
    "EventSource",
    "ExitReason",
    "FileEditSource",
    "FileReadSource",
    "RecallType",
    "RuntimeStatus",
    "ActionConfirmationStatus",
    "ActionSecurityRisk",
    # Retry
    "RetryConfig",
    "RetryStrategy",
]
