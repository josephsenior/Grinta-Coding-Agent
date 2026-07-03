"""Flat acceptance criteria persistence and normalization."""

from backend.core.criteria.acceptance_criteria_store import AcceptanceCriteriaStore
from backend.core.criteria.criterion_item import (
    CRITERION_SOURCE_INFERRED,
    CRITERION_SOURCE_STATED,
    assign_criterion_ids,
    backfill_criterion_ids,
    merge_ids_from_existing,
    normalize_criteria_list,
    normalize_criterion_payload,
)
from backend.core.criteria.evidence_ref import (
    EvidenceRefError,
    resolve_evidence_ref,
)

__all__ = [
    'AcceptanceCriteriaStore',
    'CRITERION_SOURCE_INFERRED',
    'CRITERION_SOURCE_STATED',
    'EvidenceRefError',
    'assign_criterion_ids',
    'backfill_criterion_ids',
    'merge_ids_from_existing',
    'normalize_criteria_list',
    'normalize_criterion_payload',
    'resolve_evidence_ref',
]
