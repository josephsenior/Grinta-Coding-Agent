"""Tests for core/schemas – base models, serialization, migration, and retry config."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone


from backend.core.enums import (
    EventSource,
    EventVersion,
    RetryStrategy,
)
from backend.core.schemas.base import (
    BaseEventSchema,
    EventMetadata,
    EventSchemaV1,
    _create_default_event_metadata,
)
from backend.core.schemas.retry import RetryConfig
from backend.core.schemas.serialization import (
    _deserialize_action,
    _deserialize_observation,
    deserialize_event,
    migrate_schema_version,
    serialize_event,
    validate_event_schema,
)


# ---------------------------------------------------------------------------
# EventMetadata
# ---------------------------------------------------------------------------
class TestEventMetadata(unittest.TestCase):
    def test_defaults(self):
        m = EventMetadata()
        self.assertIsNone(m.event_id)
        self.assertIsNone(m.sequence)
        self.assertIsNone(m.timestamp)
        self.assertIsNone(m.source)
        self.assertIsNone(m.cause)
        self.assertFalse(m.hidden)
        self.assertIsNone(m.timeout)
        self.assertIsNone(m.response_id)
        self.assertIsNone(m.trace_id)

    def test_with_values(self):
        now = datetime.now(timezone.utc)
        m = EventMetadata(
            event_id=42,
            sequence=1,
            timestamp=now,
            source=EventSource.AGENT,
            cause=10,
            hidden=True,
            timeout=5.0,
            response_id="resp-1",
            trace_id="trace-123",
        )
        self.assertEqual(m.event_id, 42)
        self.assertEqual(m.source, EventSource.AGENT.value)
        self.assertTrue(m.hidden)
        self.assertEqual(m.trace_id, "trace-123")

    def test_factory_function(self):
        m = _create_default_event_metadata()
        self.assertIsInstance(m, EventMetadata)


# ---------------------------------------------------------------------------
# BaseEventSchema / EventSchemaV1
# ---------------------------------------------------------------------------
class TestBaseEventSchema(unittest.TestCase):
    def test_default_version(self):
        e = BaseEventSchema()
        self.assertEqual(e.schema_version, EventVersion.V1.value)

    def test_to_dict(self):
        e = BaseEventSchema()
        d = e.to_dict()
        self.assertIn("schema_version", d)
        self.assertIsInstance(d, dict)

    def test_from_dict(self):
        d = {"schema_version": "1.0.0"}
        e = BaseEventSchema.from_dict(d)
        self.assertIsInstance(e, BaseEventSchema)


class TestEventSchemaV1(unittest.TestCase):
    def test_version_fixed(self):
        e = EventSchemaV1()
        self.assertEqual(e.schema_version, EventVersion.V1.value)

    def test_validator_coerces_string(self):
        e = EventSchemaV1.model_validate({"schema_version": "1.0.0"})
        self.assertIsNotNone(e)


# ---------------------------------------------------------------------------
# serialize_event / deserialize_event
# ---------------------------------------------------------------------------
class TestSerializeEvent(unittest.TestCase):
    def test_serialize_returns_json_string(self):
        e = BaseEventSchema()
        s = serialize_event(e)
        self.assertIsInstance(s, str)
        parsed = json.loads(s)
        self.assertIn("schema_version", parsed)


class TestDeserializeEvent(unittest.TestCase):
    def test_action_roundtrip(self):
        data = {
            "action_type": "message",
            "content": "hello",
        }
        event = deserialize_event(data)
        self.assertIsNotNone(event)

    def test_action_from_json_string(self):
        data = json.dumps({"action_type": "null"})
        event = deserialize_event(data)
        self.assertIsNotNone(event)

    def test_observation_roundtrip(self):
        data = {
            "observation_type": "error",
            "content": "boom",
        }
        event = deserialize_event(data)
        self.assertIsNotNone(event)

    def test_missing_type_raises(self):
        with self.assertRaises(
            ValueError, msg="must have either action_type or observation_type"
        ):
            deserialize_event({"foo": "bar"})

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            deserialize_event("{bad json}")

    def test_unknown_action_type_raises(self):
        with self.assertRaises(ValueError, msg="Unknown action type"):
            deserialize_event({"action_type": "nonexistent_action_xyz"})

    def test_unknown_observation_type_raises(self):
        with self.assertRaises(ValueError, msg="Unknown observation type"):
            deserialize_event({"observation_type": "nonexistent_obs_xyz"})

    def test_schema_version_from_data(self):
        data = {
            "action_type": "null",
            "schema_version": "1.0.0",
        }
        event = deserialize_event(data)
        self.assertIsNotNone(event)

    def test_unknown_schema_version_raises(self):
        data = {
            "action_type": "null",
            "schema_version": "99.0.0",
        }
        with self.assertRaises(ValueError):
            deserialize_event(data)


# ---------------------------------------------------------------------------
# _deserialize_action
# ---------------------------------------------------------------------------
class TestDeserializeAction(unittest.TestCase):
    def test_file_read(self):
        data = {"action_type": "read", "path": "/a.py"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_file_write(self):
        data = {"action_type": "write", "path": "/b.py", "content": "x"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_file_edit(self):
        data = {"action_type": "edit", "path": "/c.py"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_cmd_run(self):
        data = {"action_type": "run", "command": "ls"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_message(self):
        data = {"action_type": "message", "content": "hi"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_system(self):
        data = {"action_type": "system", "content": "prompt"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_browse_interactive(self):
        data = {"action_type": "browse_interactive", "browser_actions": "click()"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_finish(self):
        data = {"action_type": "finish"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_reject(self):
        data = {"action_type": "reject"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_change_agent_state(self):
        data = {"action_type": "change_agent_state", "state": "running"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_null(self):
        data = {"action_type": "null"}
        a = _deserialize_action(data)
        self.assertIsNotNone(a)

    def test_missing_action_type_raises(self):
        with self.assertRaises(ValueError):
            _deserialize_action({})


# ---------------------------------------------------------------------------
# _deserialize_observation
# ---------------------------------------------------------------------------
class TestDeserializeObservation(unittest.TestCase):
    def test_cmd_output(self):
        data = {"observation_type": "run", "command": "ls", "content": "output"}
        o = _deserialize_observation(data)
        self.assertIsNotNone(o)

    def test_file_read(self):
        data = {"observation_type": "read", "path": "/a.py", "content": "code"}
        o = _deserialize_observation(data)
        self.assertIsNotNone(o)

    def test_file_edit(self):
        data = {"observation_type": "edit", "path": "/b.py", "content": "edited"}
        o = _deserialize_observation(data)
        self.assertIsNotNone(o)

    def test_error(self):
        data = {"observation_type": "error", "content": "boom"}
        o = _deserialize_observation(data)
        self.assertIsNotNone(o)

    def test_message(self):
        data = {"observation_type": "message", "content": "hello"}
        o = _deserialize_observation(data)
        self.assertIsNotNone(o)

    def test_missing_observation_type_raises(self):
        with self.assertRaises(ValueError):
            _deserialize_observation({})

    def test_cmd_output_with_dict_cmd_metadata(self):
        data = {
            "observation_type": "run",
            "command": "echo hi",
            "content": "hi",
            "cmd_metadata": {"exit_code": 0, "pid": 123},
        }
        o = _deserialize_observation(data)
        self.assertIsNotNone(o)


# ---------------------------------------------------------------------------
# migrate_schema_version
# ---------------------------------------------------------------------------
class TestMigrateSchemaVersion(unittest.TestCase):
    def test_same_version_noop(self):
        data = {"action_type": "null"}
        result = migrate_schema_version(data, EventVersion.V1, EventVersion.V1)
        self.assertEqual(result, data)

    def test_v1_to_v2_raises(self):
        with self.assertRaises(ValueError, msg="not yet supported"):
            migrate_schema_version({}, EventVersion.V1, EventVersion.V2)

    def test_v2_to_v1_returns_copy(self):
        data = {"action_type": "null", "extra": "field"}
        result = migrate_schema_version(data, EventVersion.V2, EventVersion.V1)
        self.assertEqual(result, data)
        self.assertIsNot(result, data)  # should be a copy


# ---------------------------------------------------------------------------
# validate_event_schema
# ---------------------------------------------------------------------------
class TestValidateEventSchema(unittest.TestCase):
    def test_valid_schema(self):
        e = BaseEventSchema()
        self.assertTrue(validate_event_schema(e))


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------
class TestRetryConfig(unittest.TestCase):
    def test_defaults(self):
        rc = RetryConfig()
        self.assertEqual(rc.max_attempts, 3)
        self.assertEqual(rc.initial_delay, 1.0)
        self.assertEqual(rc.max_delay, 60.0)
        self.assertEqual(rc.exponential_base, 2.0)
        self.assertTrue(rc.jitter)
        self.assertEqual(rc.jitter_range, (0.0, 0.3))
        self.assertEqual(rc.strategy, RetryStrategy.EXPONENTIAL)
        self.assertIsNone(rc.on_retry)

    def test_custom_values(self):
        cb = lambda attempt, exc: None  # noqa: E731
        rc = RetryConfig(
            max_attempts=5,
            initial_delay=0.5,
            max_delay=30.0,
            exponential_base=3.0,
            jitter=False,
            jitter_range=(0.1, 0.5),
            strategy=RetryStrategy.LINEAR,
            retryable_exceptions=(ValueError, TypeError),
            on_retry=cb,
        )
        self.assertEqual(rc.max_attempts, 5)
        self.assertEqual(rc.strategy, RetryStrategy.LINEAR)
        self.assertFalse(rc.jitter)
        self.assertEqual(rc.retryable_exceptions, (ValueError, TypeError))
        self.assertIs(rc.on_retry, cb)

    def test_strategy_variants(self):
        for strat in RetryStrategy:
            rc = RetryConfig(strategy=strat)
            self.assertEqual(rc.strategy, strat)


if __name__ == "__main__":
    unittest.main()
