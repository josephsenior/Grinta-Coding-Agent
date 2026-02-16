"""Unit tests for backend.utils.search_utils — pagination helpers."""

from __future__ import annotations

import base64

import pytest

from backend.utils.search_utils import offset_to_page_id, page_id_to_offset


# ---------------------------------------------------------------------------
# offset_to_page_id
# ---------------------------------------------------------------------------


class TestOffsetToPageId:
    def test_has_next(self):
        pid = offset_to_page_id(42, has_next=True)
        assert pid is not None
        # Decode to verify
        decoded = int(base64.b64decode(pid).decode())
        assert decoded == 42

    def test_no_next(self):
        assert offset_to_page_id(42, has_next=False) is None

    def test_zero_offset(self):
        pid = offset_to_page_id(0, has_next=True)
        assert pid is not None
        decoded = int(base64.b64decode(pid).decode())
        assert decoded == 0


# ---------------------------------------------------------------------------
# page_id_to_offset
# ---------------------------------------------------------------------------


class TestPageIdToOffset:
    def test_none_returns_zero(self):
        assert page_id_to_offset(None) == 0

    def test_roundtrip(self):
        for val in [0, 1, 100, 999]:
            pid = offset_to_page_id(val, has_next=True)
            assert page_id_to_offset(pid) == val

    def test_encoded_value(self):
        encoded = base64.b64encode(b"50").decode()
        assert page_id_to_offset(encoded) == 50
