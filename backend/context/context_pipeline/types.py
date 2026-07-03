"""Split submodule — see package facade for public API."""

from __future__ import annotations

from dataclasses import dataclass

_LAST_BOUNDARY_COMPACT_KEY = 'last_boundary_compact_at'
_LAST_LLM_STEP_KEY = 'last_llm_step_at'
_JUST_COMPACTED_KEY = 'just_compacted'
_SKIP_COMPACTION_UNTIL_KEY = 'skip_compaction_until_event_id'
_INEFFECTIVE_COMPACT_STREAK_KEY = 'ineffective_compact_streak'
_INEFFECTIVE_COMPACT_UNTIL_KEY = 'ineffective_compact_until'
_CONSECUTIVE_CONDENSATION_KEY = 'consecutive_condensation_steps'
_CONSECUTIVE_DECAY_SECONDS_KEY = 'consecutive_condensation_decay_seconds'
_COMPACTION_TARGET_RATIO = 0.7

# consecutive-condensation counter is telemetry / decay only — not a skip gate.
_CONSECUTIVE_CONDENSATION_DECAY_SECONDS = 30.0
_POST_COMPACT_TRUE_TOKENS_KEY = 'post_compact_true_tokens'
# Logged when post-compact estimate is still over threshold; not a skip gate.
_WILL_RETRIGGER_HYSTERESIS_KEY = 'will_retrigger_hysteresis'
_AUTOCOMPACT_FAILURE_STREAK_KEY = 'autocompact_failure_streak'
_MAX_AUTOCOMPACT_FAILURES = 3
_MAX_LLM_COMPACTION_ATTEMPTS = 3


@dataclass(frozen=True)
class _ContinuityGateDecision:
    passed: bool
    canonical_ok: bool
    fingerprint: str
    missing: tuple[str, ...]
    score: float
    matched: int
    total: int
