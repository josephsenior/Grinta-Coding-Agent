"""Continuity checks for compacted conversation recovery.

The goal is to make compaction quality measurable: given the full event stream
and the text restored after compaction, verify that high-value coding-agent
facts still survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context.pre_condensation_snapshot import extract_snapshot
from backend.core.constants import DEFAULT_CONTINUITY_GATE_MIN_SCORE

if TYPE_CHECKING:
    from backend.ledger.event import Event

_CRITICAL_CONTINUITY_CATEGORIES = frozenset(
    {'test_result', 'decision', 'failed_approach'}
)


@dataclass(frozen=True)
class ContinuityFact:
    """A semantic fact that should survive condensation."""

    category: str
    key: str
    expected_text: str


@dataclass(frozen=True)
class ContinuityEvalResult:
    """Score for how well restored compacted context preserves key facts."""

    total: int
    matched: int
    missing: tuple[ContinuityFact, ...]
    score: float

    @property
    def passed(self) -> bool:
        return not self.missing


def _extract_file_facts(files: object, facts: list[ContinuityFact]) -> None:
    if not isinstance(files, dict):
        return
    for path, info in files.items():
        if not isinstance(path, str) or not path:
            continue
        facts.append(ContinuityFact('file', path, path))
        if isinstance(info, dict):
            file_hash = info.get('sha256')
            if isinstance(file_hash, str) and file_hash:
                facts.append(
                    ContinuityFact('file_hash', path, f'sha256:{file_hash[:16]}')
                )


def _extract_string_fact_facts(
    snapshot: dict, key: str, category: str, facts: list[ContinuityFact]
) -> None:
    for item in _string_items(snapshot.get(key, [])):
        facts.append(ContinuityFact(category, item[:80], item[:200]))


def _extract_test_result_facts(snapshot: dict, facts: list[ContinuityFact]) -> None:
    for result in _dict_items(snapshot.get('test_results', [])):
        command = str(result.get('command', '')).strip()
        status = str(result.get('status', '')).upper()
        exit_code = result.get('exit_code')
        if command:
            facts.append(
                ContinuityFact(
                    'test_result',
                    command[:80],
                    f'{status} (exit={exit_code}): {command}',
                )
            )


def _extract_failed_approach_facts(snapshot: dict, facts: list[ContinuityFact]) -> None:
    for approach in _dict_items(snapshot.get('attempted_approaches', [])):
        outcome = str(approach.get('outcome', '')).strip()
        detail = str(approach.get('detail', '')).strip()
        if detail and 'FAILED' in outcome:
            facts.append(ContinuityFact('failed_approach', detail[:80], detail))
            facts.append(ContinuityFact('failed_outcome', detail[:80], outcome))


def build_continuity_facts(events: list[Event]) -> tuple[ContinuityFact, ...]:
    """Extract coding-agent facts that should remain visible after compaction."""
    snapshot = extract_snapshot(events)
    facts: list[ContinuityFact] = []

    _extract_file_facts(snapshot.get('files_touched', {}), facts)
    _extract_string_fact_facts(snapshot, 'invalidated_assumptions', 'invalidated_assumption', facts)
    _extract_string_fact_facts(snapshot, 'decisions', 'decision', facts)
    _extract_string_fact_facts(snapshot, 'recent_errors', 'error', facts)
    _extract_test_result_facts(snapshot, facts)
    _extract_failed_approach_facts(snapshot, facts)

    return tuple(facts)


def compaction_passes_continuity_gate(
    events: list[Event],
    restored_context: str,
    *,
    min_score: float = DEFAULT_CONTINUITY_GATE_MIN_SCORE,
) -> tuple[bool, ContinuityEvalResult]:
    """Return whether a pending compaction preserves critical coding-agent facts."""
    result = evaluate_restored_context(events, restored_context)
    critical_missing = tuple(
        fact
        for fact in result.missing
        if fact.category in _CRITICAL_CONTINUITY_CATEGORIES
    )
    if critical_missing:
        return False, result
    if result.total == 0:
        return True, result
    return result.score >= min_score, result


def evaluate_restored_context(
    events: list[Event],
    restored_context: str,
) -> ContinuityEvalResult:
    """Compare original-event facts against restored compacted context text."""
    facts = build_continuity_facts(events)
    haystack = _normalize(restored_context)
    missing = tuple(fact for fact in facts if not _fact_present(fact, haystack))
    matched = len(facts) - len(missing)
    score = 1.0 if not facts else matched / len(facts)
    return ContinuityEvalResult(
        total=len(facts),
        matched=matched,
        missing=missing,
        score=score,
    )


def _fact_present(fact: ContinuityFact, normalized_context: str) -> bool:
    expected = _normalize(fact.expected_text)
    if not expected:
        return True
    if expected in normalized_context:
        return True
    # Long free-form notes are often clipped by the restored-context formatter.
    return len(expected) > 120 and expected[:120] in normalized_context


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text).casefold()).strip()


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _dict_items(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


__all__ = [
    'ContinuityEvalResult',
    'ContinuityFact',
    'build_continuity_facts',
    'compaction_passes_continuity_gate',
    'evaluate_restored_context',
]
