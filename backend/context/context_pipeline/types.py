"""Split submodule — see package facade for public API."""

from __future__ import annotations

from dataclasses import dataclass

_LAST_LLM_STEP_KEY = 'last_llm_step_at'
_JUST_COMPACTED_KEY = 'just_compacted'
_POST_COMPACT_TRUE_TOKENS_KEY = 'post_compact_true_tokens'
_EXPLICIT_COMPACT_DISMISSED_REQUEST_ID_KEY = 'explicit_compact_dismissed_request_id'
_MAX_LLM_COMPACTION_ATTEMPTS = 2


@dataclass(frozen=True)
class _ContinuityGateDecision:
    passed: bool
    canonical_ok: bool
    fingerprint: str
    missing: tuple[str, ...]
    score: float
    matched: int
    total: int
