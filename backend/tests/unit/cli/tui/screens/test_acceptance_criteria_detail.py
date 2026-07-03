"""Tests for acceptance criteria detail helpers."""

from __future__ import annotations

from types import SimpleNamespace

from backend.cli.tui.screens.detail.helpers import (
    criteria_rows_from_observation,
    format_criterion_line,
)


def test_format_criterion_line_includes_source_and_evidence() -> None:
    line = format_criterion_line(
        {
            'assertion': 'Build succeeds',
            'source': 'stated',
            'evidence': 'pytest green',
        }
    )
    assert line == '(stated) Build succeeds — pytest green'


def test_criteria_rows_from_observation_prefers_structured_list() -> None:
    obs = SimpleNamespace(
        criteria_list=[{'assertion': 'Tests pass', 'source': 'stated'}],
        content='# Acceptance Criteria\n\n1. (inferred) Other\n',
    )
    rows = criteria_rows_from_observation(obs)
    assert len(rows) == 1
    assert rows[0]['assertion'] == 'Tests pass'


def test_criteria_rows_from_observation_parses_markdown_fallback() -> None:
    obs = SimpleNamespace(
        criteria_list=[],
        content=(
            '# Acceptance Criteria\n\n'
            '1. (stated) Build succeeds\n'
            '2. (inferred) Docs updated — README section added\n'
        ),
    )
    rows = criteria_rows_from_observation(obs)
    assert len(rows) == 2
    assert rows[0]['assertion'] == 'Build succeeds'
    assert rows[1]['evidence'] == 'README section added'
