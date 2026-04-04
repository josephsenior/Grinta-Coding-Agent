"""Tests for backend.ledger.serialization.common — shared constants."""

from backend.ledger.serialization.common import COMMON_METADATA_FIELDS, UNDERSCORE_KEYS


class TestSerializationCommon:
    """Verify the shared constants haven't drifted from expected values."""

    def test_common_metadata_fields(self):
        assert isinstance(COMMON_METADATA_FIELDS, tuple)
        assert 'id' in COMMON_METADATA_FIELDS
        assert 'timestamp' in COMMON_METADATA_FIELDS
        assert 'source' in COMMON_METADATA_FIELDS
        assert 'cause' in COMMON_METADATA_FIELDS
        assert 'tool_call_metadata' in COMMON_METADATA_FIELDS
        assert 'sequence' in COMMON_METADATA_FIELDS

    def test_underscore_keys_contains_metadata(self):
        """UNDERSCORE_KEYS is a superset of COMMON_METADATA_FIELDS."""
        assert isinstance(UNDERSCORE_KEYS, list)
        for field in COMMON_METADATA_FIELDS:
            assert field in UNDERSCORE_KEYS

    def test_underscore_keys_extras(self):
        """UNDERSCORE_KEYS adds llm_metrics and reason."""
        assert 'llm_metrics' in UNDERSCORE_KEYS
        assert 'reason' in UNDERSCORE_KEYS
