"""Normalization for flat acceptance-criteria payloads."""

from __future__ import annotations

from typing import Any

CRITERION_SOURCE_STATED = 'stated'
CRITERION_SOURCE_INFERRED = 'inferred'

_VALID_SOURCES = frozenset({CRITERION_SOURCE_STATED, CRITERION_SOURCE_INFERRED})


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

    return {
        'assertion': assertion,
        'source': source,
        'evidence': evidence,
    }


def normalize_criteria_list(items: list[Any]) -> list[dict[str, Any]]:
    """Normalize a list of criterion payloads."""
    return [normalize_criterion_payload(item) for item in items]


__all__ = [
    'CRITERION_SOURCE_INFERRED',
    'CRITERION_SOURCE_STATED',
    'normalize_criteria_list',
    'normalize_criterion_payload',
]
