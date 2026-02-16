"""Tests for backend.memory.memory_types — Decision, ContextAnchor, enums."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.memory.memory_types import (
    ContextAnchor,
    Decision,
    DecisionType,
    MemoryTier,
)


# ===================================================================
# Enums
# ===================================================================

class TestDecisionType:

    def test_all_values(self):
        expected = {
            "architectural", "implementation", "technical",
            "functional", "constraint", "workflow",
        }
        assert {e.value for e in DecisionType} == expected


class TestMemoryTier:

    def test_all_values(self):
        assert MemoryTier.SHORT_TERM.value == "short_term"
        assert MemoryTier.WORKING.value == "working"
        assert MemoryTier.LONG_TERM.value == "long_term"


# ===================================================================
# Decision
# ===================================================================

class TestDecision:

    @pytest.fixture()
    def sample_decision(self) -> Decision:
        return Decision(
            decision_id="d-1",
            type=DecisionType.ARCHITECTURAL,
            description="Use microservices",
            rationale="Better scaling",
            timestamp=datetime(2025, 1, 15, 10, 30, 0),
            context="Initial planning",
            alternatives_considered=["monolith"],
            confidence=0.85,
            tier=MemoryTier.LONG_TERM,
            anchor=True,
        )

    def test_to_dict(self, sample_decision: Decision):
        d = sample_decision.to_dict()
        assert d["decision_id"] == "d-1"
        assert d["type"] == "architectural"
        assert d["confidence"] == 0.85
        assert d["tier"] == "long_term"
        assert d["anchor"] is True
        assert d["alternatives_considered"] == ["monolith"]
        assert d["timestamp"] == "2025-01-15T10:30:00"

    def test_from_dict_roundtrip(self, sample_decision: Decision):
        d = sample_decision.to_dict()
        restored = Decision.from_dict(d)
        assert restored.decision_id == sample_decision.decision_id
        assert restored.type == sample_decision.type
        assert restored.description == sample_decision.description
        assert restored.confidence == sample_decision.confidence
        assert restored.tier == sample_decision.tier
        assert restored.anchor == sample_decision.anchor

    def test_from_dict_defaults(self):
        minimal = {
            "decision_id": "d-2",
            "type": "implementation",
            "description": "Use pytest",
            "rationale": "Better fixtures",
            "timestamp": "2025-06-01T12:00:00",
            "context": "Testing setup",
        }
        dec = Decision.from_dict(minimal)
        assert dec.alternatives_considered == []
        assert dec.confidence == 1.0
        assert dec.tier == MemoryTier.WORKING
        assert dec.anchor is False

    def test_default_field_values(self):
        dec = Decision(
            decision_id="x",
            type=DecisionType.TECHNICAL,
            description="desc",
            rationale="why",
            timestamp=datetime.now(),
            context="ctx",
        )
        assert dec.alternatives_considered == []
        assert dec.confidence == 1.0
        assert dec.tier == MemoryTier.WORKING
        assert dec.anchor is False


# ===================================================================
# ContextAnchor
# ===================================================================

class TestContextAnchor:

    @pytest.fixture()
    def sample_anchor(self) -> ContextAnchor:
        now = datetime(2025, 3, 20, 8, 0, 0)
        return ContextAnchor(
            anchor_id="a-1",
            content="Must support Python 3.12+",
            category="constraint",
            importance=0.95,
            timestamp=now,
            last_accessed=now,
            access_count=5,
        )

    def test_to_dict(self, sample_anchor: ContextAnchor):
        d = sample_anchor.to_dict()
        assert d["anchor_id"] == "a-1"
        assert d["content"] == "Must support Python 3.12+"
        assert d["category"] == "constraint"
        assert d["importance"] == 0.95
        assert d["access_count"] == 5

    def test_from_dict_roundtrip(self, sample_anchor: ContextAnchor):
        d = sample_anchor.to_dict()
        restored = ContextAnchor.from_dict(d)
        assert restored.anchor_id == sample_anchor.anchor_id
        assert restored.content == sample_anchor.content
        assert restored.importance == sample_anchor.importance
        assert restored.access_count == sample_anchor.access_count

    def test_from_dict_defaults(self):
        data = {
            "anchor_id": "a-2",
            "content": "Must be fast",
            "category": "requirement",
            "importance": 0.5,
            "timestamp": "2025-01-01T00:00:00",
            "last_accessed": "2025-01-01T00:00:00",
        }
        anchor = ContextAnchor.from_dict(data)
        assert anchor.access_count == 0

    def test_default_access_count(self):
        now = datetime.now()
        anchor = ContextAnchor(
            anchor_id="a-3",
            content="test",
            category="goal",
            importance=0.7,
            timestamp=now,
            last_accessed=now,
        )
        assert anchor.access_count == 0
