"""Tests for acceptance criteria store refine helpers."""

from __future__ import annotations

import pytest

from backend.core.criteria.acceptance_criteria_store import build_refined_criteria_list


def test_build_refined_criteria_list_appends_change_log():
    existing = [
        {
            'id': 'ac1',
            'assertion': 'Timeout is 3 ticks',
            'source': 'inferred',
            'evidence': None,
        }
    ]
    updated = build_refined_criteria_list(
        existing,
        criterion_id='ac1',
        new_assertion='Timeout is 5 ticks on WSL',
        reason='3 ticks too short on WSL',
        changed_at='2026-07-03T12:00:00Z',
    )
    assert updated[0]['assertion'] == 'Timeout is 5 ticks on WSL'
    assert updated[0]['source'] == 'inferred'
    assert updated[0]['changes'][0]['reason'] == '3 ticks too short on WSL'


def test_build_refined_criteria_list_unknown_id():
    with pytest.raises(KeyError, match='ac9'):
        build_refined_criteria_list(
            [{'id': 'ac1', 'assertion': 'A', 'source': 'stated'}],
            criterion_id='ac9',
            new_assertion='B',
            reason='why',
            changed_at='2026-07-03T12:00:00Z',
        )
