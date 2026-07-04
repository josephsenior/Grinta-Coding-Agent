"""Split submodule — see package facade for public API."""

from __future__ import annotations

from dataclasses import dataclass

_LAST_BOUNDARY_COMPACT_KEY = 'last_boundary_compact_at'
_LAST_LLM_STEP_KEY = 'last_llm_step_at'
_JUST_COMPACTED_KEY = 'just_compacted'
_CONSECUTIVE_CONDENSATION_KEY = 'consecutive_condensation_steps'
_POST_COMPACT_TRUE_TOKENS_KEY = 'post_compact_true_tokens'
# Telemetry only — logged when post-compact estimate is still over threshold.
_WILL_RETRIGGER_HYSTERESIS_KEY = 'will_retrigger_hysteresis'
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
