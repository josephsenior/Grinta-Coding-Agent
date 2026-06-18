"""Split submodule — see package facade for public API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    pass


_LAST_LLM_COMPACT_KEY = 'last_llm_compact_attempt'
_LAST_BOUNDARY_COMPACT_KEY = 'last_boundary_compact_at'
_JUST_COMPACTED_KEY = 'just_compacted'
_SKIP_COMPACTION_UNTIL_KEY = 'skip_compaction_until_event_id'
_INEFFECTIVE_COMPACT_STREAK_KEY = 'ineffective_compact_streak'
_INEFFECTIVE_COMPACT_UNTIL_KEY = 'ineffective_compact_until'
_CONSECUTIVE_CONDENSATION_KEY = 'consecutive_condensation_steps'
_CONTINUITY_REJECTION_FP_KEY = 'last_continuity_rejection_fingerprint'
_CONTINUITY_REJECTION_STREAK_KEY = 'continuity_rejection_streak'
_DETERMINISTIC_FALLBACK_THRESHOLD = 2
_COMPACTION_TARGET_RATIO = 0.7


@dataclass
class PipelineStepResult:
    """Processed events for prompt build plus optional pending condensation."""

    events: list[Event]
    pending_action: CondensationAction | None = None
    compacted: bool = False


@dataclass(frozen=True)
class _ContinuityGateDecision:
    passed: bool
    canonical_ok: bool
    fingerprint: str
    missing: tuple[str, ...]
    score: float
    matched: int
    total: int
