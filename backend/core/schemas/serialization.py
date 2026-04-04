"""Serialization and deserialization for App event schemas with version migration."""

from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from backend.core import json_compat as json
from backend.core.schemas.actions import ActionSchemaUnion
from backend.core.schemas.base import BaseEventSchema, EventVersion
from backend.core.schemas.observations import ObservationSchemaUnion


def serialize_event(event: BaseEventSchema) -> str:
    """Serialize an event schema to JSON string.

    Args:
        event: Event schema to serialize

    Returns:
        JSON string representation of the event

    Raises:
        ValueError: If event cannot be serialized
    """
    try:
        return json.dumps(event.to_dict(), default=str)
    except Exception as e:
        raise ValueError(f'Failed to serialize event: {e}') from e


def deserialize_event(
    data: str | dict[str, Any], version: EventVersion | None = None
) -> BaseEventSchema:
    """Deserialize an event schema from JSON string or dictionary.

    Args:
        data: JSON string or dictionary containing event data
        version: Optional schema version to use (defaults to version in data)

    Returns:
        Deserialized event schema

    Raises:
        ValueError: If event cannot be deserialized
    """
    if isinstance(data, str):
        try:
            data_dict = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f'Failed to parse JSON: {e}') from e
    else:
        data_dict = data

    # Migrate to latest version if needed
    if version is None:
        schema_version = data_dict.get('schema_version', EventVersion.V1)
        if isinstance(schema_version, str):
            try:
                version = EventVersion(schema_version)
            except ValueError:
                version = EventVersion.V1
        else:
            version = EventVersion.V1

    # Migrate schema if needed
    if version != EventVersion.V1:
        data_dict = migrate_schema_version(data_dict, version, EventVersion.V1)

    # Determine event type and deserialize
    try:
        # Try action schemas first
        if 'action_type' in data_dict:
            return _deserialize_action(data_dict)
        # Try observation schemas
        if 'observation_type' in data_dict:
            return _deserialize_observation(data_dict)
        raise ValueError('Event must have either action_type or observation_type')
    except ValidationError as e:
        raise ValueError(f'Failed to validate event schema: {e}') from e


def _deserialize_action(data: dict[str, Any]) -> ActionSchemaUnion:
    """Deserialize an action schema from dictionary.

    Args:
        data: Dictionary containing action data

    Returns:
        Deserialized action schema

    Raises:
        ValueError: If action type is unknown or validation fails
    """
    from backend.core.schemas.actions import (
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

    action_type = data.get('action_type')
    if not action_type:
        raise ValueError('Action must have action_type field')

    action_schemas: dict[str, type[BaseEventSchema]] = {
        'read': FileReadActionSchema,
        'write': FileWriteActionSchema,
        'edit': FileEditActionSchema,
        'run': CmdRunActionSchema,
        'message': MessageActionSchema,
        'system': SystemMessageActionSchema,
        'browse_interactive': BrowseInteractiveActionSchema,
        'finish': PlaybookFinishActionSchema,
        'reject': AgentRejectActionSchema,
        'change_agent_state': ChangeAgentStateActionSchema,
        'null': NullActionSchema,
    }

    schema_class = action_schemas.get(action_type)
    if not schema_class:
        raise ValueError(f'Unknown action type: {action_type}')

    return cast(ActionSchemaUnion, schema_class.model_validate(data))


def _deserialize_observation(data: dict[str, Any]) -> ObservationSchemaUnion:
    """Deserialize an observation schema from dictionary.

    Args:
        data: Dictionary containing observation data

    Returns:
        Deserialized observation schema

    Raises:
        ValueError: If observation type is unknown or validation fails
    """
    from backend.core.schemas.observations import (
        CmdOutputObservationSchema,
        ErrorObservationSchema,
        FileEditObservationSchema,
        FileReadObservationSchema,
        MessageObservationSchema,
    )

    observation_type = data.get('observation_type')
    if not observation_type:
        raise ValueError('Observation must have observation_type field')

    observation_schemas: dict[str, type[BaseEventSchema]] = {
        'run': CmdOutputObservationSchema,
        'read': FileReadObservationSchema,
        'edit': FileEditObservationSchema,
        'error': ErrorObservationSchema,
        'message': MessageObservationSchema,
    }

    schema_class = observation_schemas.get(observation_type)
    if not schema_class:
        raise ValueError(f'Unknown observation type: {observation_type}')

    # Handle cmd_metadata conversion for CmdOutputObservation
    # Note: metadata field is for EventMetadata, cmd_metadata is for CmdOutputMetadata
    if observation_type == 'run' and 'cmd_metadata' in data:
        cmd_metadata = data['cmd_metadata']
        # If cmd_metadata is already a dict, keep it as is
        # Pydantic will handle validation
        if not isinstance(cmd_metadata, dict):
            # Try to convert to dict if it's a Pydantic model
            if hasattr(cmd_metadata, 'model_dump'):
                data['cmd_metadata'] = cmd_metadata.model_dump()
            elif hasattr(cmd_metadata, '__dict__'):
                data['cmd_metadata'] = cmd_metadata.__dict__

    return cast(ObservationSchemaUnion, schema_class.model_validate(data))


def migrate_schema_version(
    data: dict[str, Any], from_version: EventVersion, to_version: EventVersion
) -> dict[str, Any]:
    """Migrate event schema from one version to another.

    Args:
        data: Event data dictionary
        from_version: Source schema version
        to_version: Target schema version

    Returns:
        Migrated event data dictionary

    Raises:
        ValueError: If migration is not supported
    """
    if from_version == to_version:
        return data

    # V1 to V2 migration (placeholder for future)
    if from_version == EventVersion.V1 and to_version == EventVersion.V2:
        # Add migration logic here when V2 is introduced
        raise ValueError(
            f'Migration from {from_version} to {to_version} is not yet supported'
        )

    # V2 to V1 migration (downgrade)
    if from_version == EventVersion.V2 and to_version == EventVersion.V1:
        # Remove V2-specific fields
        return data.copy()
        # Add downgrade logic here when V2 is introduced

    raise ValueError(f'Migration from {from_version} to {to_version} is not supported')


def validate_event_schema(event: BaseEventSchema) -> bool:
    """Validate an event schema.

    Args:
        event: Event schema to validate

    Returns:
        True if event is valid

    Raises:
        ValueError: If event is invalid
    """
    try:
        event.__class__.model_validate(event.to_dict())
        return True
    except ValidationError as e:
        raise ValueError(f'Event schema validation failed: {e}') from e
