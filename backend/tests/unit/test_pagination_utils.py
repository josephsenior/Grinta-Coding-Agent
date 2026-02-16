"""Tests for backend.utils.search_utils — Pagination offset/page_id helpers."""

from __future__ import annotations

import base64

import pytest

from backend.utils.search_utils import offset_to_page_id, page_id_to_offset


class TestOffsetToPageIdUnit:
    def test_has_next_true(self):
        result = offset_to_page_id(42, has_next=True)
        assert result is not None
        assert base64.b64decode(result).decode() == "42"

    def test_has_next_false(self):
        assert offset_to_page_id(42, has_next=False) is None

    def test_zero_offset(self):
        result = offset_to_page_id(0, has_next=True)
        assert base64.b64decode(result).decode() == "0"

    def test_large_offset(self):
        result = offset_to_page_id(999999, has_next=True)
        assert base64.b64decode(result).decode() == "999999"


class TestPageIdToOffsetUnit:
    def test_none_returns_zero(self):
        assert page_id_to_offset(None) == 0

    def test_empty_string_returns_zero(self):
        assert page_id_to_offset("") == 0

    def test_round_trip(self):
        page_id = offset_to_page_id(100, has_next=True)
        assert page_id_to_offset(page_id) == 100

    def test_round_trip_zero(self):
        page_id = offset_to_page_id(0, has_next=True)
        assert page_id_to_offset(page_id) == 0
