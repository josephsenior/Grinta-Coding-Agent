"""Normalization for flat acceptance-criteria payloads."""

from __future__ import annotations

import re
from typing import Any

CRITERION_SOURCE_STATED = 'stated'
CRITERION_SOURCE_INFERRED = 'inferred'

_VALID_SOURCES = frozenset({CRITERION_SOURCE_STATED, CRITERION_SOURCE_INFERRED})
_CRITERION_ID_RE = re.compile(r'^ac(\d+)$', re.IGNORECASE)


def normalize_criterion_payload(item: Any) -> dict[str, Any]:
    """Normalize a single acceptance criterion to the canonical schema."""
    if not isinstance(item, dict):
        msg = f'Criterion must be a dictionary, got {type(item)}'
        raise TypeError(msg)

    assertion = str(item.get('assertion') or '').strip()
    if not assertion:
        msg = "Criterion 'assertion' is required and must be non-empty"
        raise TypeError(msg)

    source = str(item.get('source') or CRITERION_SOURCE_STATED).strip().lower()
    if source not in _VALID_SOURCES:
        msg = f"Criterion 'source' must be one of: {', '.join(sorted(_VALID_SOURCES))}"
        raise TypeError(msg)

    evidence_raw = item.get('evidence')
    evidence: str | None
    if evidence_raw is None:
        evidence = None
    else:
        evidence = str(evidence_raw).strip() or None

    evidence_ref_raw = item.get('evidence_ref')
    evidence_ref: str | None
    if evidence_ref_raw is None:
        evidence_ref = None
    else:
        evidence_ref = str(evidence_ref_raw).strip() or None

    criterion_id = str(item.get('id') or '').strip() or None

    result: dict[str, Any] = {
        'id': criterion_id,
        'assertion': assertion,
        'source': source,
        'evidence': evidence,
        'evidence_ref': evidence_ref,
    }

    changes = item.get('changes')
    if isinstance(changes, list) and changes:
        result['changes'] = _normalize_changes(changes)

    return result


def _normalize_changes(changes: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for entry in changes:
        if not isinstance(entry, dict):
            continue
        old_assertion = str(entry.get('old_assertion') or '').strip()
        new_assertion = str(entry.get('new_assertion') or '').strip()
        reason = str(entry.get('reason') or '').strip()
        at = str(entry.get('at') or '').strip()
        if not old_assertion or not new_assertion or not reason:
            continue
        row: dict[str, str] = {
            'old_assertion': old_assertion,
            'new_assertion': new_assertion,
            'reason': reason,
        }
        if at:
            row['at'] = at
        normalized.append(row)
    return normalized


def normalize_criteria_list(items: list[Any]) -> list[dict[str, Any]]:
    """Normalize a list of criterion payloads."""
    return [normalize_criterion_payload(item) for item in items]


def _max_criterion_id_number(items: list[dict[str, Any]]) -> int:
    max_n = 0
    for item in items:
        raw_id = str(item.get('id') or '').strip()
        match = _CRITERION_ID_RE.match(raw_id)
        if match:
            max_n = max(max_n, int(match.group(1)))
    return max_n


def assign_criterion_ids(
    items: list[dict[str, Any]],
    *,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assign stable ``ac{N}`` ids to criteria missing them."""
    seed = _max_criterion_id_number(list(existing or []) + list(items))
    next_n = seed + 1
    result: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        if not str(row.get('id') or '').strip():
            row['id'] = f'ac{next_n}'
            next_n += 1
        result.append(row)
    return result


def merge_ids_from_existing(
    incoming: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve ids by position when incoming items omit them."""
    merged: list[dict[str, Any]] = []
    for index, item in enumerate(incoming):
        row = dict(item)
        if not str(row.get('id') or '').strip() and index < len(existing):
            row['id'] = str(existing[index].get('id') or '').strip() or None
        merged.append(row)
    return assign_criterion_ids(merged, existing=existing)


def backfill_criterion_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every persisted criterion has a stable id."""
    return assign_criterion_ids(normalize_criteria_list(items))


__all__ = [
    'CRITERION_SOURCE_INFERRED',
    'CRITERION_SOURCE_STATED',
    'assign_criterion_ids',
    'backfill_criterion_ids',
    'merge_ids_from_existing',
    'normalize_criteria_list',
    'normalize_criterion_payload',
]
