"""Tests for backend.core.schemas.base — Event schema models."""

from __future__ import annotations

from backend.core.enums import EventSource, EventVersion
from backend.core.schemas.base import (
    BaseEventSchema,
    EventMetadata,
    EventSchemaV1,
)

# ── EventMetadata ────────────────────────────────────────────────────


class TestEventMetadata:
    def test_defaults(self):
        m = EventMetadata()
        assert m.event_id is None
        assert m.sequence is None
        assert m.timestamp is None
        assert m.source is None
        assert m.cause is None
        assert m.hidden is False
        assert m.timeout is None
        assert m.response_id is None
        assert m.trace_id is None

    def test_custom_values(self):
        m = EventMetadata(
            event_id=1,
            sequence=5,
            hidden=True,
            source=EventSource.AGENT,
            timeout=30.0,
        )
        assert m.event_id == 1
        assert m.sequence == 5
        assert m.hidden is True
        assert m.timeout == 30.0


# ── BaseEventSchema ─────────────────────────────────────────────────


class TestBaseEventSchema:
    def test_defaults(self):
        schema = BaseEventSchema()
        assert (
            schema.schema_version == EventVersion.V1 or schema.schema_version == '1.0.0'
        )

    def test_to_dict(self):
        schema = BaseEventSchema()
        d = schema.to_dict()
        assert isinstance(d, dict)
        assert 'schema_version' in d

    def test_from_dict_roundtrip(self):
        original = BaseEventSchema()
        d = original.to_dict()
        restored = BaseEventSchema.from_dict(d)
        assert restored.to_dict() == d

    def test_to_dict_excludes_none(self):
        schema = BaseEventSchema()
        d = schema.to_dict()
        # metadata fields that are None should be excluded
        meta = d.get('metadata', {})
        assert 'event_id' not in meta

    def test_with_metadata(self):
        m = EventMetadata(event_id=42, hidden=True)
        schema = BaseEventSchema(metadata=m)
        d = schema.to_dict()
        assert d['metadata']['event_id'] == 42
        assert d['metadata']['hidden'] is True


# ── EventSchemaV1 ────────────────────────────────────────────────────


class TestEventSchemaV1:
    def test_version_is_v1(self):
        schema = EventSchemaV1()
        assert (
            schema.schema_version == EventVersion.V1 or schema.schema_version == '1.0.0'
        )

    def test_validate_version_from_string(self):
        schema = EventSchemaV1.model_validate({'schema_version': '1.0.0'})
        assert (
            schema.schema_version == EventVersion.V1 or schema.schema_version == '1.0.0'
        )

    def test_roundtrip(self):
        original = EventSchemaV1()
        d = original.to_dict()
        restored = EventSchemaV1.from_dict(d)
        assert restored.to_dict() == d
