"""Tests for memory observation processor utilities."""

from unittest.mock import MagicMock


from backend.events.observation import Observation
from backend.memory.observation_processors import (
    _get_observation_content,
    _is_valid_image_url,
)


class TestGetObservationContent:
    def test_observation_with_content_string(self):
        """Test extracting content from observation with content attribute."""
        obs = MagicMock(spec=Observation)
        obs.content = "test content"
        result = _get_observation_content(obs)
        assert result == "test content"

    def test_observation_with_message_string(self):
        """Test extracting content from observation with message attribute."""
        obs = MagicMock(spec=Observation)
        # Remove content attribute
        del obs.content
        obs.message = "test message"

        result = _get_observation_content(obs)
        assert result == "test message"

    def test_observation_with_both_content_and_message(self):
        """Test that content takes precedence over message."""
        obs = MagicMock(spec=Observation)
        obs.content = "content wins"
        obs.message = "message loses"

        result = _get_observation_content(obs)
        assert result == "content wins"

    def test_observation_with_non_string_content(self):
        """Test handling non-string content attribute."""
        obs = MagicMock(spec=Observation)
        obs.content = 12345  # Not a string

        result = _get_observation_content(obs)
        # Should fall through to str(obs)
        assert isinstance(result, str)

    def test_observation_with_no_content_or_message(self):
        """Test fallback to str() when no content/message."""
        obs = MagicMock(spec=Observation)
        # Remove both attributes
        del obs.content
        del obs.message

        result = _get_observation_content(obs)
        # Should call str(obs)
        assert isinstance(result, str)

    def test_observation_with_empty_string_content(self):
        """Test observation with empty string content."""
        obs = MagicMock(spec=Observation)
        obs.content = ""

        result = _get_observation_content(obs)
        assert result == ""

    def test_observation_with_whitespace_content(self):
        """Test observation with whitespace content."""
        obs = MagicMock(spec=Observation)
        obs.content = "   \n\t   "

        result = _get_observation_content(obs)
        assert result == "   \n\t   "


class TestIsValidImageUrl:
    def test_valid_url_string(self):
        """Test valid non-empty URL string."""
        result = _is_valid_image_url("https://example.com/image.png")
        assert result is True

    def test_valid_data_url(self):
        """Test valid data URL."""
        result = _is_valid_image_url("data:image/png;base64,iVBORw0KGgo...")
        assert result is True

    def test_none_url(self):
        """Test None URL."""
        result = _is_valid_image_url(None)
        assert result is False

    def test_empty_string_url(self):
        """Test empty string URL."""
        result = _is_valid_image_url("")
        assert result is False

    def test_whitespace_only_url(self):
        """Test whitespace-only URL."""
        result = _is_valid_image_url("   \n\t   ")
        assert result is False

    def test_single_space_url(self):
        """Test single space URL."""
        result = _is_valid_image_url(" ")
        assert result is False

    def test_non_string_url(self):
        """Test non-string URL."""
        result = _is_valid_image_url(12345)  # type: ignore
        assert result is False

    def test_simple_filename(self):
        """Test simple filename string."""
        result = _is_valid_image_url("image.png")
        assert result is True

    def test_relative_path(self):
        """Test relative path."""
        result = _is_valid_image_url("./images/test.jpg")
        assert result is True

    def test_absolute_path(self):
        """Test absolute path."""
        result = _is_valid_image_url("/var/www/images/test.jpg")
        assert result is True

    def test_url_with_spaces(self):
        """Test URL with leading/trailing spaces (should still be valid after strip)."""
        result = _is_valid_image_url("  https://example.com/image.png  ")
        assert result is True

    def test_windows_path(self):
        """Test Windows path."""
        result = _is_valid_image_url("C:\\Users\\test\\image.png")
        assert result is True
