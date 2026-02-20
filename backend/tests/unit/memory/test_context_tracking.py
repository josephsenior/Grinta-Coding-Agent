"""Tests for backend.memory.context_tracking — decision and anchor tracking."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock


from backend.memory.context_tracking import ContextTracker
from backend.memory.graph_store import GraphMemoryStore, NodeType
from backend.memory.memory_types import DecisionType


class TestContextTrackerInit:
    """Tests for ContextTracker initialization."""

    def test_init_without_vector_store(self):
        """Test initializes with no vector store."""
        tracker = ContextTracker()
        assert tracker.vector_store is None
        assert tracker.decisions == {}
        assert tracker.anchors == {}

    def test_init_with_vector_store(self):
        """Test initializes with provided vector store."""
        mock_store = MagicMock()
        tracker = ContextTracker(vector_store=mock_store)
        assert tracker.vector_store is mock_store
        assert tracker.decisions == {}
        assert tracker.anchors == {}


class TestGraphRAGWiring:
    def test_store_in_memory_indexes_graph(self, tmp_path):
        mock_store = MagicMock()
        graph_store = GraphMemoryStore(persistence_path=str(tmp_path / "graph.json"))
        tracker = ContextTracker(vector_store=mock_store, graph_store=graph_store)

        tracker.store_in_memory(
            event_id="e1",
            role="observation",
            content="import os\nfrom foo import bar\n",
            metadata={"file_path": "example.py"},
        )

        assert graph_store.graph.has_node("example.py")

    def test_recall_from_memory_prepends_graph_rag_context(self, tmp_path):
        mock_store = MagicMock()
        # Ensure semantic search returns a seed with file_path metadata
        mock_store.search.return_value = [
            {
                "content_text": "something about the file",
                "metadata": {"file_path": "example.py"},
            }
        ]
        graph_store = GraphMemoryStore(persistence_path=str(tmp_path / "graph.json"))
        tracker = ContextTracker(vector_store=mock_store, graph_store=graph_store)

        # Create a minimal node so graph expansion doesn't error.
        graph_store.add_node("example.py", NodeType.FILE)

        results = tracker.recall_from_memory("example", k=3)
        assert results
        assert results[0]["role"] == "graph_rag"
        assert "### Semantic Matches" in results[0]["content_text"]


class TestTrackDecision:
    """Tests for track_decision method."""

    def test_creates_decision_with_all_fields(self):
        """Test creates Decision object with all provided fields."""
        tracker = ContextTracker()

        decision = tracker.track_decision(
            description="Use pattern X",
            rationale="Best performance",
            decision_type=DecisionType.ARCHITECTURAL,
            context="Working on module Y",
            confidence=0.95,
        )

        assert decision.description == "Use pattern X"
        assert decision.rationale == "Best performance"
        assert decision.type == DecisionType.ARCHITECTURAL
        assert decision.context == "Working on module Y"
        assert decision.confidence == 0.95
        assert isinstance(decision.timestamp, datetime)

    def test_generates_unique_decision_ids(self):
        """Test each decision gets a unique ID."""
        tracker = ContextTracker()

        d1 = tracker.track_decision(
            description="Decision 1",
            rationale="Reason 1",
            decision_type=DecisionType.IMPLEMENTATION,
            context="Context 1",
        )
        d2 = tracker.track_decision(
            description="Decision 2",
            rationale="Reason 2",
            decision_type=DecisionType.IMPLEMENTATION,
            context="Context 2",
        )

        assert d1.decision_id != d2.decision_id
        assert "decision_1_" in d1.decision_id
        assert "decision_2_" in d2.decision_id

    def test_stores_decision_in_dict(self):
        """Test stores decision in internal dict by ID."""
        tracker = ContextTracker()

        decision = tracker.track_decision(
            description="Test decision",
            rationale="Test rationale",
            decision_type=DecisionType.TECHNICAL,
            context="Test context",
        )

        assert decision.decision_id in tracker.decisions
        assert tracker.decisions[decision.decision_id] == decision

    def test_default_confidence_is_one(self):
        """Test confidence defaults to 1.0 when not provided."""
        tracker = ContextTracker()

        decision = tracker.track_decision(
            description="Test",
            rationale="Test",
            decision_type=DecisionType.IMPLEMENTATION,
            context="Test",
        )

        assert decision.confidence == 1.0

    def test_multiple_decisions_accumulate(self):
        """Test multiple decisions are stored without overwriting."""
        tracker = ContextTracker()

        d1 = tracker.track_decision("D1", "R1", DecisionType.ARCHITECTURAL, "C1")
        d2 = tracker.track_decision("D2", "R2", DecisionType.IMPLEMENTATION, "C2")
        d3 = tracker.track_decision("D3", "R3", DecisionType.TECHNICAL, "C3")

        assert len(tracker.decisions) == 3
        assert all(d.decision_id in tracker.decisions for d in [d1, d2, d3])


class TestAddAnchor:
    """Tests for add_anchor method."""

    def test_creates_anchor_with_all_fields(self):
        """Test creates ContextAnchor with all provided fields."""
        tracker = ContextTracker()

        anchor = tracker.add_anchor(
            content="Critical requirement X",
            category="requirement",
            importance=0.95,
        )

        assert anchor.content == "Critical requirement X"
        assert anchor.category == "requirement"
        assert anchor.importance == 0.95
        assert isinstance(anchor.timestamp, datetime)
        assert isinstance(anchor.last_accessed, datetime)

    def test_generates_unique_anchor_ids(self):
        """Test each anchor gets a unique ID."""
        tracker = ContextTracker()

        a1 = tracker.add_anchor("Anchor 1", "category1")
        a2 = tracker.add_anchor("Anchor 2", "category2")

        assert a1.anchor_id != a2.anchor_id
        assert "anchor_1_" in a1.anchor_id
        assert "anchor_2_" in a2.anchor_id

    def test_stores_anchor_in_dict(self):
        """Test stores anchor in internal dict by ID."""
        tracker = ContextTracker()

        anchor = tracker.add_anchor("Test content", "test_category")

        assert anchor.anchor_id in tracker.anchors
        assert tracker.anchors[anchor.anchor_id] == anchor

    def test_default_importance_is_point_nine(self):
        """Test importance defaults to 0.9 when not provided."""
        tracker = ContextTracker()

        anchor = tracker.add_anchor("Test", "category")

        assert anchor.importance == 0.9

    def test_multiple_anchors_accumulate(self):
        """Test multiple anchors are stored without overwriting."""
        tracker = ContextTracker()

        a1 = tracker.add_anchor("Content 1", "cat1", 0.8)
        a2 = tracker.add_anchor("Content 2", "cat2", 0.9)
        a3 = tracker.add_anchor("Content 3", "cat3", 1.0)

        assert len(tracker.anchors) == 3
        assert all(a.anchor_id in tracker.anchors for a in [a1, a2, a3])


class TestGetContextSummary:
    """Tests for get_context_summary method."""

    def test_empty_tracker_returns_empty_string(self):
        """Test returns empty string when no anchors or decisions exist."""
        tracker = ContextTracker()
        assert tracker.get_context_summary() == ""

    def test_anchors_only_returns_anchor_section(self):
        """Test returns anchor section when only anchors exist."""
        tracker = ContextTracker()
        tracker.add_anchor("Important requirement", "requirement", 0.95)
        tracker.add_anchor("Secondary note", "note", 0.7)

        summary = tracker.get_context_summary()

        assert "## Critical Context (Anchors)" in summary
        assert "[REQUIREMENT]" in summary
        assert "Important requirement" in summary
        assert "[NOTE]" in summary
        assert "Secondary note" in summary
        assert "## Recent Decisions" not in summary

    def test_decisions_only_returns_decision_section(self):
        """Test returns decision section when only decisions exist."""
        tracker = ContextTracker()
        tracker.track_decision(
            "Use approach X",
            "Better performance",
            DecisionType.ARCHITECTURAL,
            "Context A",
        )

        summary = tracker.get_context_summary()

        assert "## Recent Decisions" in summary
        assert "Use approach X" in summary
        assert "Better performance" in summary
        assert "## Critical Context (Anchors)" not in summary

    def test_both_anchors_and_decisions_returns_both_sections(self):
        """Test returns both sections when both exist."""
        tracker = ContextTracker()
        tracker.add_anchor("Key requirement", "requirement")
        tracker.track_decision(
            "Use pattern Y",
            "Simplicity",
            DecisionType.IMPLEMENTATION,
            "Context B",
        )

        summary = tracker.get_context_summary()

        assert "## Critical Context (Anchors)" in summary
        assert "## Recent Decisions" in summary
        assert "Key requirement" in summary
        assert "Use pattern Y" in summary

    def test_anchors_sorted_by_importance_descending(self):
        """Test anchors are sorted by importance (highest first)."""
        tracker = ContextTracker()
        tracker.add_anchor("Low importance", "cat", 0.5)
        tracker.add_anchor("High importance", "cat", 0.99)
        tracker.add_anchor("Medium importance", "cat", 0.7)

        summary = tracker.get_context_summary()

        # High should appear before medium before low
        high_idx = summary.index("High importance")
        medium_idx = summary.index("Medium importance")
        low_idx = summary.index("Low importance")

        assert high_idx < medium_idx < low_idx

    def test_decisions_sorted_by_timestamp_newest_first(self):
        """Test decisions are sorted by timestamp (newest first)."""
        tracker = ContextTracker()

        # Track in order: old, middle, new
        d1 = tracker.track_decision(
            "Old decision", "R1", DecisionType.ARCHITECTURAL, "C1"
        )
        d2 = tracker.track_decision(
            "Middle decision", "R2", DecisionType.IMPLEMENTATION, "C2"
        )
        d3 = tracker.track_decision("New decision", "R3", DecisionType.WORKFLOW, "C3")

        # Manually adjust timestamps to ensure ordering
        d1.timestamp = datetime(2024, 1, 1)
        d2.timestamp = datetime(2024, 6, 1)
        d3.timestamp = datetime(2024, 12, 1)

        summary = tracker.get_context_summary()

        new_idx = summary.index("New decision")
        middle_idx = summary.index("Middle decision")
        old_idx = summary.index("Old decision")

        assert new_idx < middle_idx < old_idx

    def test_limits_decisions_to_five_most_recent(self):
        """Test only includes 5 most recent decisions."""
        tracker = ContextTracker()

        # Create 10 decisions
        for i in range(10):
            tracker.track_decision(
                f"Decision {i}",
                f"Rationale {i}",
                DecisionType.IMPLEMENTATION,
                f"Context {i}",
            )

        summary = tracker.get_context_summary()

        # Should have exactly 5 decisions (last 5 created)
        decision_lines = [
            line
            for line in summary.split("\n")
            if line.startswith("- ") and "Rationale" in line
        ]
        assert len(decision_lines) == 5


class TestStoreInMemory:
    """Tests for store_in_memory method."""

    def test_does_nothing_when_no_vector_store(self):
        """Test returns early when vector store is None."""
        tracker = ContextTracker()
        # Should not raise
        tracker.store_in_memory("event1", "user", "content")

    def test_calls_vector_store_add_with_correct_params(self):
        """Test calls vector_store.add with correct parameters."""
        mock_store = MagicMock()
        tracker = ContextTracker(vector_store=mock_store)

        tracker.store_in_memory(
            "evt123",
            "assistant",
            "Response content",
            {"key": "value"},
        )

        mock_store.add.assert_called_once_with(
            step_id="evt123",
            role="assistant",
            artifact_hash=None,
            rationale=None,
            content_text="Response content",
            metadata={"key": "value"},
        )

    def test_uses_empty_dict_when_metadata_is_none(self):
        """Test passes empty dict when metadata is None."""
        mock_store = MagicMock()
        tracker = ContextTracker(vector_store=mock_store)

        tracker.store_in_memory("evt1", "user", "Content")

        call_kwargs = mock_store.add.call_args[1]
        assert call_kwargs["metadata"] == {}

    def test_handles_vector_store_exception(self):
        """Test catches and logs exception from vector store."""
        mock_store = MagicMock()
        mock_store.add.side_effect = RuntimeError("Storage failed")

        tracker = ContextTracker(vector_store=mock_store)

        # Should not raise
        tracker.store_in_memory("evt1", "user", "Content")


class TestRecallFromMemory:
    """Tests for recall_from_memory method."""

    def test_returns_empty_list_when_no_vector_store(self):
        """Test returns empty list when vector store is None."""
        tracker = ContextTracker()
        results = tracker.recall_from_memory("query")
        assert results == []

    def test_calls_vector_store_search_with_query_and_k(self):
        """Test calls vector_store.search with correct parameters."""
        mock_store = MagicMock()
        mock_store.search.return_value = [
            {"content": "result1"},
            {"content": "result2"},
        ]

        tracker = ContextTracker(vector_store=mock_store)
        results = tracker.recall_from_memory("test query", k=10)

        mock_store.search.assert_called_once_with("test query", k=10)
        assert results == [{"content": "result1"}, {"content": "result2"}]

    def test_default_k_is_five(self):
        """Test k defaults to 5 when not provided."""
        mock_store = MagicMock()
        mock_store.search.return_value = []

        tracker = ContextTracker(vector_store=mock_store)
        tracker.recall_from_memory("query")

        mock_store.search.assert_called_once_with("query", k=5)

    def test_handles_vector_store_exception(self):
        """Test returns empty list when vector store raises exception."""
        mock_store = MagicMock()
        mock_store.search.side_effect = RuntimeError("Search failed")

        tracker = ContextTracker(vector_store=mock_store)
        results = tracker.recall_from_memory("query")

        assert results == []
