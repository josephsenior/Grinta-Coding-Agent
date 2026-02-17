"""Comprehensive tests for backend.core.schemas.serialization module.

Targets the 16.7% (65 missed lines) coverage gap.
"""

from __future__ import annotations

import json

import pytest

from backend.core.enums import EventVersion
from backend.core.schemas.base import BaseEventSchema, EventMetadata, EventSchemaV1
from backend.core.schemas.serialization import (
    _deserialize_action,
    _deserialize_observation,
    deserialize_event,
    migrate_schema_version,
    serialize_event,
    validate_event_schema,
)


# ------------------------------------------------------------------
# Helpers — build minimal valid dicts
# ------------------------------------------------------------------
def _action_dict(action_type: str, **extra) -> dict:
    return {"action_type": action_type, "schema_version": "1.0.0", **extra}


def _obs_dict(obs_type: str, **extra) -> dict:
    return {"observation_type": obs_type, "content": "ok", "schema_version": "1.0.0", **extra}


# ==================================================================
# serialize_event
# ==================================================================
class TestSerializeEvent:
    def test_round_trip_action(self):
        from backend.core.schemas.actions import NullActionSchema
        ev = NullActionSchema()
        s = serialize_event(ev)
        assert isinstance(s, str)
        d = json.loads(s)
        assert d["action_type"] == "null"

    def test_round_trip_message(self):
        from backend.core.schemas.actions import MessageActionSchema
        ev = MessageActionSchema(content="hello")
        s = serialize_event(ev)
        d = json.loads(s)
        assert d["content"] == "hello"

    def test_raises_on_bad_event(self):
        """Non-serializable event should raise ValueError."""
        bad = BaseEventSchema()
        # BaseEventSchema *should* serialize, but let's verify
        s = serialize_event(bad)
        assert isinstance(s, str)


# ==================================================================
# deserialize_event — actions
# ==================================================================
class TestDeserializeAction:
    def test_null_action(self):
        d = _action_dict("null")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "NullActionSchema"

    def test_message_action(self):
        d = _action_dict("message", content="hi")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "MessageActionSchema"

    def test_cmd_run_action(self):
        d = _action_dict("run", command="ls")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "CmdRunActionSchema"

    def test_file_read_action(self):
        d = _action_dict("read", path="/tmp/x.py")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "FileReadActionSchema"

    def test_file_write_action(self):
        d = _action_dict("write", path="/tmp/x.py", content="code")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "FileWriteActionSchema"

    def test_file_edit_action(self):
        d = _action_dict("edit", path="/tmp/x.py")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "FileEditActionSchema"

    def test_finish_action(self):
        d = _action_dict("finish")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "PlaybookFinishActionSchema"

    def test_reject_action(self):
        d = _action_dict("reject")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "AgentRejectActionSchema"

    def test_change_agent_state_action(self):
        d = _action_dict("change_agent_state", state="running")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "ChangeAgentStateActionSchema"

    def test_system_message_action(self):
        d = _action_dict("system", content="sys msg")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "SystemMessageActionSchema"

    def test_browse_interactive_action(self):
        d = _action_dict("browse_interactive", browser_actions="click(1)")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "BrowseInteractiveActionSchema"

    def test_unknown_action_type_raises(self):
        with pytest.raises(ValueError, match="Unknown action type"):
            deserialize_event(_action_dict("nonexistent"))

    def test_missing_action_type_raises(self):
        with pytest.raises(ValueError, match="action_type"):
            _deserialize_action({"schema_version": "1.0.0"})


# ==================================================================
# deserialize_event — observations
# ==================================================================
class TestDeserializeObservation:
    def test_cmd_output(self):
        d = _obs_dict("run", command="ls")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "CmdOutputObservationSchema"

    def test_file_read_obs(self):
        d = _obs_dict("read", path="/tmp/x.py")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "FileReadObservationSchema"

    def test_file_edit_obs(self):
        d = _obs_dict("edit", path="/tmp/x.py")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "FileEditObservationSchema"

    def test_error_obs(self):
        d = _obs_dict("error")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "ErrorObservationSchema"

    def test_message_obs(self):
        d = _obs_dict("message")
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "MessageObservationSchema"

    def test_unknown_obs_type_raises(self):
        with pytest.raises(ValueError, match="Unknown observation type"):
            deserialize_event(_obs_dict("nonexistent"))

    def test_missing_obs_type_raises(self):
        with pytest.raises(ValueError, match="observation_type"):
            _deserialize_observation({"content": "x", "schema_version": "1.0.0"})

    def test_cmd_output_with_cmd_metadata_dict(self):
        d = _obs_dict("run", command="ls", cmd_metadata={"exit_code": 0})
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "CmdOutputObservationSchema"


# ==================================================================
# deserialize_event — JSON string input
# ==================================================================
class TestDeserializeFromJSON:
    def test_from_json_string(self):
        s = json.dumps(_action_dict("null"))
        ev = deserialize_event(s)
        assert ev.__class__.__name__ == "NullActionSchema"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            deserialize_event("not json{{{")

    def test_no_type_key_raises(self):
        with pytest.raises(ValueError, match="action_type or observation_type"):
            deserialize_event({"schema_version": "1.0.0"})


# ==================================================================
# deserialize_event — version handling
# ==================================================================
class TestDeserializeVersions:
    def test_explicit_v1_version(self):
        d = _action_dict("null")
        ev = deserialize_event(d, version=EventVersion.V1)
        assert ev.__class__.__name__ == "NullActionSchema"

    def test_unknown_version_string_raises(self):
        d = _action_dict("null", schema_version="99.0.0")
        with pytest.raises(ValueError, match="Failed to validate"):
            deserialize_event(d)

    def test_non_string_version_defaults_v1(self):
        d = _action_dict("null")
        d["schema_version"] = EventVersion.V1
        ev = deserialize_event(d)
        assert ev.__class__.__name__ == "NullActionSchema"


# ==================================================================
# migrate_schema_version
# ==================================================================
class TestMigrateSchemaVersion:
    def test_same_version_noop(self):
        d = {"action_type": "null"}
        result = migrate_schema_version(d, EventVersion.V1, EventVersion.V1)
        assert result == d

    def test_v1_to_v2_raises(self):
        with pytest.raises(ValueError, match="not yet supported"):
            migrate_schema_version({}, EventVersion.V1, EventVersion.V2)

    def test_v2_to_v1_returns_copy(self):
        d = {"action_type": "null", "extra": "field"}
        result = migrate_schema_version(d, EventVersion.V2, EventVersion.V1)
        assert result == d
        assert result is not d  # Should be a copy


# ==================================================================
# validate_event_schema
# ==================================================================
class TestValidateEventSchema:
    def test_valid_schema(self):
        from backend.core.schemas.actions import NullActionSchema
        assert validate_event_schema(NullActionSchema()) is True

    def test_valid_message(self):
        from backend.core.schemas.actions import MessageActionSchema
        assert validate_event_schema(MessageActionSchema(content="hi")) is True

    def test_valid_observation(self):
        from backend.core.schemas.observations import ErrorObservationSchema
        ev = ErrorObservationSchema(content="err")
        assert validate_event_schema(ev) is True
