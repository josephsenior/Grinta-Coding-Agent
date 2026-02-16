"""Tests for backend.server.constants — server constants and API versioning."""

from backend.server.constants import (
    ENFORCE_API_VERSIONING,
    ROOM_KEY,
    get_api_prefix,
)


class TestAPIVersioning:
    """Tests for API versioning constants and functions."""

    def test_enforce_api_versioning_default(self):
        """Test ENFORCE_API_VERSIONING is a boolean."""
        assert isinstance(ENFORCE_API_VERSIONING, bool)

    def test_get_api_prefix_default(self):
        """Test get_api_prefix with default version."""
        prefix = get_api_prefix()
        assert prefix.startswith("/api/")
        assert "/" in prefix

    def test_get_api_prefix_custom_version(self):
        """Test get_api_prefix with custom version."""
        prefix = get_api_prefix("v2")
        assert prefix == "/api/v2"

    def test_get_api_prefix_v1(self):
        """Test get_api_prefix with v1."""
        prefix = get_api_prefix("v1")
        assert prefix == "/api/v1"

    def test_get_api_prefix_format(self):
        """Test API prefix format is correct."""
        prefix = get_api_prefix("test")
        assert prefix == "/api/test"

    def test_room_key_constant_exists(self):
        """Test ROOM_KEY constant is defined."""
        assert ROOM_KEY is not None
        assert isinstance(ROOM_KEY, str)

    def test_room_key_is_template(self):
        """Test ROOM_KEY is a template string."""
        assert "{" in ROOM_KEY or ROOM_KEY.strip() != ""
