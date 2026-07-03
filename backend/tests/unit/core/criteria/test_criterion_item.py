"""Tests for criterion payload normalization."""

from __future__ import annotations

import pytest

from backend.core.criteria.criterion_item import (
    CRITERION_SOURCE_INFERRED,
    normalize_criteria_list,
    normalize_criterion_payload,
)


class TestNormalizeCriterionPayload:
    def test_minimal(self):
        item = normalize_criterion_payload(
            {'assertion': 'Throws on invalid input', 'source': 'stated'}
        )
        assert item['assertion'] == 'Throws on invalid input'
        assert item['source'] == 'stated'
        assert item['evidence'] is None

    def test_inferred_default_evidence(self):
        item = normalize_criterion_payload(
            {
                'assertion': 'Edge case handled',
                'source': CRITERION_SOURCE_INFERRED,
                'evidence': 'test_foo.py::test_edge',
            }
        )
        assert item['evidence'] == 'test_foo.py::test_edge'

    def test_rejects_empty_assertion(self):
        with pytest.raises(TypeError, match='assertion'):
            normalize_criterion_payload({'source': 'stated'})

    def test_normalize_list(self):
        items = normalize_criteria_list(
            [
                {'assertion': 'A', 'source': 'stated'},
                {'assertion': 'B', 'source': 'inferred'},
            ]
        )
        assert len(items) == 2
