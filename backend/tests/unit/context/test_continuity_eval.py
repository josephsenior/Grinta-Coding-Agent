"""Continuity eval tests for compacted conversation recovery."""

from __future__ import annotations

from backend.context.compactor.pre_condensation_snapshot import (
    extract_snapshot,
    format_snapshot_for_injection,
)
from backend.context.continuity_eval import (
    build_continuity_facts,
    compaction_passes_continuity_gate,
    evaluate_restored_context,
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


def test_compaction_continuity_gate_blocks_missing_test_result():
    events = _coding_session_events()
    restored = format_snapshot_for_injection(extract_snapshot(events))
    restored = restored.replace('python -m pytest backend/tests/unit/context -q', '')

    passed, result = compaction_passes_continuity_gate(events, restored)

    assert not passed
    assert any(f.category == 'test_result' for f in result.missing)


def test_compaction_continuity_gate_passes_for_complete_snapshot():
    events = _coding_session_events()
    restored = format_snapshot_for_injection(extract_snapshot(events))

    passed, result = compaction_passes_continuity_gate(events, restored)

    assert passed
    assert result.passed


def test_compaction_gate_demotes_noncritical_missing_text_to_telemetry():
    events = _coding_session_events()
    restored = format_snapshot_for_injection(extract_snapshot(events))
    restored = restored.replace('Use token-budget-aware backward assembly.', '')

    passed, result = compaction_passes_continuity_gate(events, restored)

    assert passed
    assert not result.passed
    assert any(f.category == 'decision' for f in result.missing)


def test_compaction_continuity_gate_blocks_missing_failed_approach():
    """Losing a 'do not retry' failed-approach fact must block compaction."""
    events = _coding_session_events()
    snapshot = extract_snapshot(events)
    restored = format_snapshot_for_injection(snapshot)

    # Remove the failed-approach detail from the restored context.
    failed = [
        a
        for a in snapshot.get('attempted_approaches', [])
        if 'FAILED' in str(a.get('outcome', ''))
    ]
    assert failed, 'fixture must contain at least one failed approach'
    detail = str(failed[-1].get('detail', ''))
    assert detail
    restored_missing = restored.replace(detail, '')

    passed, result = compaction_passes_continuity_gate(events, restored_missing)

    assert not passed
    assert any(f.category == 'failed_approach' for f in result.missing)


def test_compaction_continuity_gate_allows_missing_transient_error():
    """A dropped transient error stays telemetry; it must not block."""
    events = _coding_session_events()
    restored = format_snapshot_for_injection(extract_snapshot(events))
    restored_missing = restored.replace(
        'cache served a stale prompt after file edit', ''
    )

    passed, result = compaction_passes_continuity_gate(events, restored_missing)

    assert passed
    # Still reported as missing for observability, just not blocking.
    assert any(f.category == 'error' for f in result.missing)


def test_fallback_summary_retains_failed_approaches():
    """The snapshot injection (used by the deterministic fallback) keeps
    failed-approach facts, so rejecting a lossy summary is quality-safe.
    """
    events = _coding_session_events()
    snapshot = extract_snapshot(events)
    restored = format_snapshot_for_injection(snapshot)

    failed = [
        a
        for a in snapshot.get('attempted_approaches', [])
        if 'FAILED' in str(a.get('outcome', ''))
    ]
    assert failed
    detail = str(failed[-1].get('detail', ''))
    assert detail and detail in restored


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
