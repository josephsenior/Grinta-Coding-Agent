"""Tests for search pagination utilities."""

import base64

from backend.utils.search_utils import offset_to_page_id, page_id_to_offset


class TestOffsetToPageId:
    def test_offset_with_next_page(self):
        """Test encoding offset when there is a next page."""
        result = offset_to_page_id(100, has_next=True)
        assert result is not None
        # Decode to verify it's correct
        decoded = base64.b64decode(result).decode()
        assert decoded == "100"

    def test_offset_without_next_page(self):
        """Test encoding offset when there is no next page."""
        result = offset_to_page_id(100, has_next=False)
        assert result is None

    def test_zero_offset_with_next(self):
        """Test encoding zero offset with next page."""
        result = offset_to_page_id(0, has_next=True)
        assert result is not None
        decoded = base64.b64decode(result).decode()
        assert decoded == "0"

    def test_zero_offset_without_next(self):
        """Test encoding zero offset without next page."""
        result = offset_to_page_id(0, has_next=False)
        assert result is None

    def test_large_offset(self):
        """Test encoding large offset value."""
        result = offset_to_page_id(999999, has_next=True)
        assert result is not None
        decoded = base64.b64decode(result).decode()
        assert decoded == "999999"

    def test_negative_offset(self):
        """Test encoding negative offset (unusual but should work)."""
        result = offset_to_page_id(-10, has_next=True)
        assert result is not None
        decoded = base64.b64decode(result).decode()
        assert decoded == "-10"


class TestPageIdToOffset:
    def test_none_page_id(self):
        """Test decoding None page ID returns 0."""
        result = page_id_to_offset(None)
        assert result == 0

    def test_valid_page_id(self):
        """Test decoding valid page ID."""
        # Encode "100"
        page_id = base64.b64encode(b"100").decode()
        result = page_id_to_offset(page_id)
        assert result == 100

    def test_zero_page_id(self):
        """Test decoding page ID for offset 0."""
        page_id = base64.b64encode(b"0").decode()
        result = page_id_to_offset(page_id)
        assert result == 0

    def test_large_offset_page_id(self):
        """Test decoding large offset from page ID."""
        page_id = base64.b64encode(b"999999").decode()
        result = page_id_to_offset(page_id)
        assert result == 999999

    def test_negative_offset_page_id(self):
        """Test decoding negative offset from page ID."""
        page_id = base64.b64encode(b"-10").decode()
        result = page_id_to_offset(page_id)
        assert result == -10


class TestRoundTrip:
    def test_roundtrip_with_next(self):
        """Test encoding then decoding with next page."""
        offset = 50
        page_id = offset_to_page_id(offset, has_next=True)
        assert page_id is not None
        result = page_id_to_offset(page_id)
        assert result == offset

    def test_roundtrip_zero(self):
        """Test roundtrip for zero offset."""
        offset = 0
        page_id = offset_to_page_id(offset, has_next=True)
        assert page_id is not None
        result = page_id_to_offset(page_id)
        assert result == offset

    def test_roundtrip_large_offset(self):
        """Test roundtrip for large offset."""
        offset = 123456
        page_id = offset_to_page_id(offset, has_next=True)
        assert page_id is not None
        result = page_id_to_offset(page_id)
        assert result == offset

    def test_multiple_sequential_offsets(self):
        """Test roundtrip for sequential offsets."""
        for offset in [0, 10, 20, 30, 40, 50]:
            page_id = offset_to_page_id(offset, has_next=True)
            assert page_id is not None
            result = page_id_to_offset(page_id)
            assert result == offset

    def test_none_handling(self):
        """Test that has_next=False results in None which decodes to 0."""
        page_id = offset_to_page_id(100, has_next=False)
        assert page_id is None
        result = page_id_to_offset(page_id)
        assert result == 0
