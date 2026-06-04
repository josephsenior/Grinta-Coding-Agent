"""Continuity eval tests for compacted conversation recovery."""

from __future__ import annotations

from backend.context.continuity_eval import (
    build_continuity_facts,
    evaluate_restored_context,
)
from backend.context.pre_condensation_snapshot import (
    extract_snapshot,
    format_snapshot_for_injection,
)
from backend.ledger.action.agent import AgentThinkAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileEditObservation, FileReadObservation


def _coding_session_events():
    return [
        FileReadObservation(
            path='backend/context/prompt_window.py',
            content='def select_prompt_events():\n    pass\n',
        ),
        FileEditObservation(
            content='edited',
            path='backend/context/prompt_window.py',
            new_content='def select_prompt_events():\n    return []\n',
            new_content_hash='abc123def4567890ffff',
        ),
        AgentThinkAction(
            thought='Assumption invalidated: a fixed recent N turns window was enough.'
        ),
        AgentThinkAction(thought='Use token-budget-aware backward assembly.'),
        CmdRunAction(command='python -m pytest backend/tests/unit/context -q'),
        CmdOutputObservation(
            content='FAILED test_prompt_window.py::test_preserves_summary',
            command='python -m pytest backend/tests/unit/context -q',
            exit_code=1,
        ),
        ErrorObservation(content='cache served a stale prompt after file edit'),
    ]


def test_continuity_eval_passes_for_formatted_snapshot():
    events = _coding_session_events()
    restored = format_snapshot_for_injection(extract_snapshot(events))

    result = evaluate_restored_context(events, restored)

    assert result.passed
    assert result.score == 1.0
    assert result.matched == result.total
    categories = {fact.category for fact in build_continuity_facts(events)}
    assert {
        'file',
        'file_hash',
        'invalidated_assumption',
        'decision',
        'test_result',
        'failed_approach',
        'failed_outcome',
        'error',
    } <= categories


def test_continuity_eval_reports_missing_semantic_fact():
    events = _coding_session_events()
    restored = format_snapshot_for_injection(extract_snapshot(events))
    restored = restored.replace(
        'Assumption invalidated: a fixed recent N turns window was enough.',
        '',
    )

    result = evaluate_restored_context(events, restored)

    assert not result.passed
    assert result.score < 1.0
    assert any(f.category == 'invalidated_assumption' for f in result.missing)
