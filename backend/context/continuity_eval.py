"""Continuity checks for compacted conversation recovery.

The goal is to make compaction quality measurable: given the full event stream
and the text restored after compaction, verify that high-value coding-agent
facts still survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context.compactor.pre_condensation_snapshot import (
    MAX_FILES_IN_COMPACT_SNAPSHOT,
    extract_snapshot,
)
from backend.core.constants import DEFAULT_CONTINUITY_GATE_MIN_SCORE

if TYPE_CHECKING:
    from backend.ledger.event import Event

# Categories whose loss from restored context ALWAYS degrades compaction
# quality and is therefore blocking. ``failed_approach``/``failed_outcome``
# encode "do not retry this" memory whose loss causes repeated-failure loops;
# their survival is guaranteed by the deterministic fallback's canonical +
# snapshot rendering, so blocking on them can only improve the quality of a
# committed compaction, never replace a good summary with a worse one.
#
# ``error`` is intentionally NOT blocking: transient errors should be allowed
# to drop on a later compaction, and forcing their retention would crowd out
# current facts. Still-active failures are covered separately by the canonical
# latest_verification validator.
_CRITICAL_CONTINUITY_CATEGORIES = frozenset(
    {'test_result', 'failed_approach', 'failed_outcome'}
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
    # Match ``_format_files_section`` / prompt reinjection — not every touched file.
    for path, info in list(files.items())[:MAX_FILES_IN_COMPACT_SNAPSHOT]:
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
    for item in _string_items(snapshot.get(key, []))[-8:]:
        facts.append(ContinuityFact(category, item[:80], item[:200]))


def _extract_test_result_facts(snapshot: dict, facts: list[ContinuityFact]) -> None:
    for result in _dict_items(snapshot.get('test_results', []))[-3:]:
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
    for approach in _dict_items(snapshot.get('attempted_approaches', []))[-8:]:
        outcome = str(approach.get('outcome', '')).strip()
        detail = str(approach.get('detail', '')).strip()
        if detail and 'FAILED' in outcome:
            facts.append(ContinuityFact('failed_approach', detail[:80], detail))
            facts.append(ContinuityFact('failed_outcome', detail[:80], outcome))


def _extract_acceptance_criteria_facts(
    snapshot: dict, facts: list[ContinuityFact]
) -> None:
    raw = snapshot.get('acceptance_criteria')
    items: list[dict] = []
    if isinstance(raw, dict):
        criteria = raw.get('criteria')
        if isinstance(criteria, list):
            items = [item for item in criteria if isinstance(item, dict)]
    for item in items[-8:]:
        assertion = str(item.get('assertion', '')).strip()
        criterion_id = str(item.get('id', '')).strip()
        if assertion:
            key = criterion_id or assertion[:80]
            facts.append(
                ContinuityFact('acceptance_criterion', key[:80], assertion[:200])
            )


def build_continuity_facts(events: list[Event]) -> tuple[ContinuityFact, ...]:
    """Extract coding-agent facts that should remain visible after compaction."""
    snapshot = extract_snapshot(events)
    facts: list[ContinuityFact] = []

    _extract_file_facts(snapshot.get('files_touched', {}), facts)
    _extract_string_fact_facts(
        snapshot, 'invalidated_assumptions', 'invalidated_assumption', facts
    )
    _extract_string_fact_facts(snapshot, 'decisions', 'decision', facts)
    _extract_string_fact_facts(snapshot, 'recent_errors', 'error', facts)
    _extract_test_result_facts(snapshot, facts)
    _extract_failed_approach_facts(snapshot, facts)
    _extract_acceptance_criteria_facts(snapshot, facts)

    return tuple(facts)


def compaction_passes_continuity_gate(
    events: list[Event],
    restored_context: str,
    *,
    min_score: float = DEFAULT_CONTINUITY_GATE_MIN_SCORE,
) -> tuple[bool, ContinuityEvalResult]:
    """Return whether a pending compaction preserves critical coding-agent facts.

    Non-critical text continuity is telemetry. The durable canonical-state
    validator is responsible for blocking current objective, directive, active
    files, blockers, background tasks, and failed-approach loss.
    """
    result = evaluate_restored_context(events, restored_context)
    critical_missing = tuple(
        fact
        for fact in result.missing
        if fact.category in _CRITICAL_CONTINUITY_CATEGORIES
    )
    if critical_missing:
        return False, result
    # Non-critical text continuity is telemetry, not a hard gate: a fuzzy
    # score must never reject a compaction that preserved every critical
    # fact, since the deterministic fallback is not necessarily richer than
    # the rejected summary for non-critical prose. We only surface a low
    # score for observability.
    if result.total and result.score < min_score:
        from backend.core.logging.logger import app_logger as logger

        logger.info(
            'Compaction continuity score below floor (score=%.2f < min=%.2f, '
            'matched=%d/%d); non-critical, not blocking',
            result.score,
            min_score,
            result.matched,
            result.total,
        )
    return True, result


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
    # Long free-form notes may be clipped by the restored-context formatter.
    # We still accept a sufficiently long head match, but require a
    # substantial prefix (>=120 chars) so a heavily-truncated fragment does
    # not get rubber-stamped as "present".
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
