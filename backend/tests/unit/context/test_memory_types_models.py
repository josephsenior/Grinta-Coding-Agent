"""Tests for backend.context.memory_types — Decision/ContextAnchor data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.context.memory_types import (
    ContextAnchor,
    Decision,
    DecisionType,
    MemoryTier,
)

# ── Enum tests ───────────────────────────────────────────────────────


class TestDecisionType:
    def test_values(self):
        assert DecisionType.ARCHITECTURAL.value == 'architectural'
        assert DecisionType.IMPLEMENTATION.value == 'implementation'
        assert DecisionType.TECHNICAL.value == 'technical'
        assert DecisionType.FUNCTIONAL.value == 'functional'
        assert DecisionType.CONSTRAINT.value == 'constraint'
        assert DecisionType.WORKFLOW.value == 'workflow'

    def test_count(self):
        assert len(DecisionType) == 6

    def test_from_value(self):
        assert DecisionType('architectural') is DecisionType.ARCHITECTURAL


class TestMemoryTier:
    def test_values(self):
        assert MemoryTier.SHORT_TERM.value == 'short_term'
        assert MemoryTier.WORKING.value == 'working'
        assert MemoryTier.LONG_TERM.value == 'long_term'

    def test_count(self):
        assert len(MemoryTier) == 3


# ── Decision dataclass ───────────────────────────────────────────────


class TestDecision:
    def _make(self, **overrides) -> Decision:
        defaults: dict[str, Any] = {
            'decision_id': 'd1',
            'type': DecisionType.TECHNICAL,
            'description': 'Use Redis',
            'rationale': 'Fast caching',
            'timestamp': datetime(2025, 1, 1, 12, 0, 0),
            'context': 'Discussing cache layer',
        }
        defaults.update(overrides)
        return Decision(**defaults)

    def test_defaults(self):
        d = self._make()
        assert d.alternatives_considered == []
        assert d.confidence == 1.0
        assert d.tier is MemoryTier.WORKING
        assert d.anchor is False

    def test_custom(self):
        d = self._make(
            alternatives_considered=['Memcached'],
            confidence=0.8,
            tier=MemoryTier.LONG_TERM,
            anchor=True,
        )
        assert d.alternatives_considered == ['Memcached']
        assert d.confidence == 0.8
        assert d.tier is MemoryTier.LONG_TERM
        assert d.anchor is True

    def test_to_dict(self):
        d = self._make()
        data = d.to_dict()
        assert data['decision_id'] == 'd1'
        assert data['type'] == 'technical'
        assert data['timestamp'] == '2025-01-01T12:00:00'
        assert data['tier'] == 'working'
        assert data['anchor'] is False

    def test_from_dict_roundtrip(self):
        original = self._make(
            alternatives_considered=['A', 'B'], confidence=0.9, anchor=True
        )
        data = original.to_dict()
        restored = Decision.from_dict(data)
        assert restored.decision_id == original.decision_id
        assert restored.type == original.type
        assert restored.timestamp == original.timestamp
        assert restored.alternatives_considered == original.alternatives_considered
        assert restored.confidence == original.confidence
        assert restored.anchor == original.anchor

    def test_from_dict_defaults(self):
        data = {
            'decision_id': 'd2',
            'type': 'architectural',
            'description': 'Microservices',
            'rationale': 'Scalability',
            'timestamp': '2025-06-15T09:30:00',
            'context': 'Design meeting',
        }
        d = Decision.from_dict(data)
        assert d.alternatives_considered == []
        assert d.confidence == 1.0
        assert d.tier is MemoryTier.WORKING
        assert d.anchor is False


# ── ContextAnchor dataclass ──────────────────────────────────────────


class TestContextAnchor:
    def _make(self, **overrides) -> ContextAnchor:
        defaults: dict[str, Any] = {
            'anchor_id': 'a1',
            'content': 'Must support 10k concurrent users',
            'category': 'requirement',
            'importance': 0.95,
            'timestamp': datetime(2025, 3, 1, 8, 0, 0),
            'last_accessed': datetime(2025, 3, 2, 10, 0, 0),
        }
        defaults.update(overrides)
        return ContextAnchor(**defaults)

    def test_defaults(self):
        a = self._make()
        assert a.access_count == 0

    def test_custom(self):
        a = self._make(access_count=5)
        assert a.access_count == 5

    def test_to_dict(self):
        a = self._make(access_count=3)
        data = a.to_dict()
        assert data['anchor_id'] == 'a1'
        assert data['category'] == 'requirement'
        assert data['importance'] == 0.95
        assert data['access_count'] == 3
        assert data['timestamp'] == '2025-03-01T08:00:00'
        assert data['last_accessed'] == '2025-03-02T10:00:00'

    def test_from_dict_roundtrip(self):
        original = self._make(access_count=7)
        data = original.to_dict()
        restored = ContextAnchor.from_dict(data)
        assert restored.anchor_id == original.anchor_id
        assert restored.content == original.content
        assert restored.importance == original.importance
        assert restored.access_count == original.access_count
        assert restored.timestamp == original.timestamp
        assert restored.last_accessed == original.last_accessed

    def test_from_dict_default_access_count(self):
        data = {
            'anchor_id': 'a2',
            'content': 'Must use PostgreSQL',
            'category': 'constraint',
            'importance': 0.8,
            'timestamp': '2025-01-01T00:00:00',
            'last_accessed': '2025-01-01T00:00:00',
        }
        a = ContextAnchor.from_dict(data)
        assert a.access_count == 0
