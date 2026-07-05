"""Tests for acceptance criterion normalization and ids."""

from __future__ import annotations

import pytest

from backend.core.criteria.criterion_item import (
    assign_criterion_ids,
    backfill_criterion_ids,
    merge_ids_from_existing,
    normalize_criterion_payload,
)


def test_normalize_preserves_optional_fields():
    item = normalize_criterion_payload(
        {
            'id': 'ac1',
            'assertion': 'Tests pass',
            'source': 'stated',
            'evidence': 'pytest ok',
            'changes': [
                {
                    'at': '2026-01-01T00:00:00Z',
                    'old_assertion': 'Old',
                    'new_assertion': 'Tests pass',
                    'reason': 'discovered real requirement',
                }
            ],
        }
    )
    assert item['id'] == 'ac1'
    assert item['evidence'] == 'pytest ok'
    assert len(item['changes']) == 1


def test_assign_criterion_ids_skips_existing_and_increments():
    items = assign_criterion_ids(
        [
            {'assertion': 'A', 'source': 'stated'},
            {'assertion': 'B', 'source': 'inferred'},
        ],
        existing=[{'id': 'ac3', 'assertion': 'X', 'source': 'stated'}],
    )
    assert items[0]['id'] == 'ac4'
    assert items[1]['id'] == 'ac5'


def test_merge_ids_from_existing_by_position():
    incoming = [{'assertion': 'Updated', 'source': 'stated'}]
    existing = [{'id': 'ac1', 'assertion': 'Old', 'source': 'stated'}]
    merged = merge_ids_from_existing(incoming, existing)
    assert merged[0]['id'] == 'ac1'


def test_backfill_criterion_ids_on_legacy_rows():
    rows = backfill_criterion_ids([{'assertion': 'Legacy', 'source': 'inferred'}])
    assert rows[0]['id'] == 'ac1'


def test_normalize_requires_assertion():
    with pytest.raises(TypeError, match='assertion'):
        normalize_criterion_payload({'source': 'stated'})
