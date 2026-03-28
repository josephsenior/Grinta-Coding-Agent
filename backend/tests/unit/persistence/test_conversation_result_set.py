"""Tests for backend.persistence.data_models.conversation_metadata_result_set."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.persistence.data_models.conversation_metadata_result_set import (
    ConversationMetadataResultSet,
)


class TestConversationMetadataResultSet:
    def test_defaults(self):
        rs = ConversationMetadataResultSet()
        assert rs.results == []
        assert rs.next_page_id is None

    def test_with_results(self):
        mock1 = MagicMock()
        mock2 = MagicMock()
        rs = ConversationMetadataResultSet(results=[mock1, mock2])
        assert len(rs.results) == 2

    def test_with_next_page(self):
        rs = ConversationMetadataResultSet(next_page_id="page2")
        assert rs.next_page_id == "page2"

    def test_full(self):
        mock = MagicMock()
        rs = ConversationMetadataResultSet(results=[mock], next_page_id="next")
        assert len(rs.results) == 1
        assert rs.next_page_id == "next"

    def test_empty_results_list_independent(self):
        """Each instance gets its own list."""
        rs1 = ConversationMetadataResultSet()
        rs2 = ConversationMetadataResultSet()
        rs1.results.append(MagicMock())
        assert not rs2.results
