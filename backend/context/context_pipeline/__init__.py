"""Unified context compaction pipeline — one ordered path for every LLM step."""

from __future__ import annotations

from backend.context.compactor.compaction_finalizer import (
    finalize_compaction_artifacts,
)
from backend.context.compactor.pre_condensation_snapshot import delete_staging_snapshot
from backend.context.context_budget import ContextBudget, record_post_compact_baseline
from backend.context.context_pipeline.pipeline import ContextPipeline, _EmptyState
from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    _latest_event_id,
    _projected_compaction_token_reduction,
    _pruned_ids,
    _select_compaction_tail,
    _shrink_tail_for_token_reduction,
    _synthetic_history_after_action,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.types import (
    _COMPACTION_TARGET_RATIO,
    _CONSECUTIVE_CONDENSATION_KEY,
    _CONTINUITY_REJECTION_FP_KEY,
    _CONTINUITY_REJECTION_STREAK_KEY,
    _DETERMINISTIC_FALLBACK_THRESHOLD,
    _INEFFECTIVE_COMPACT_STREAK_KEY,
    _INEFFECTIVE_COMPACT_UNTIL_KEY,
    _JUST_COMPACTED_KEY,
    _LAST_BOUNDARY_COMPACT_KEY,
    _LAST_LLM_COMPACT_KEY,
    _SKIP_COMPACTION_UNTIL_KEY,
    PipelineStepResult,
    _ContinuityGateDecision,
)
from backend.context.memory.session_memory import (
    build_compaction_summary,
    maybe_update,
    session_memory_exists,
)

__all__ = [
    'ContextBudget',
    'ContextPipeline',
    'PipelineStepResult',
    '_EmptyState',
    '_COMPACTION_TARGET_RATIO',
    '_CONSECUTIVE_CONDENSATION_KEY',
    '_CONTINUITY_REJECTION_FP_KEY',
    '_CONTINUITY_REJECTION_STREAK_KEY',
    '_ContinuityGateDecision',
    '_DETERMINISTIC_FALLBACK_THRESHOLD',
    '_INEFFECTIVE_COMPACT_STREAK_KEY',
    '_INEFFECTIVE_COMPACT_UNTIL_KEY',
    '_JUST_COMPACTED_KEY',
    '_LAST_BOUNDARY_COMPACT_KEY',
    '_LAST_LLM_COMPACT_KEY',
    '_SKIP_COMPACTION_UNTIL_KEY',
    '_drop_stale_prompt_state_artifacts',
    '_latest_event_id',
    '_projected_compaction_token_reduction',
    '_pruned_ids',
    '_select_compaction_tail',
    '_shrink_tail_for_token_reduction',
    '_synthetic_history_after_action',
    'apply_ineffective_compaction_backoff',
    'build_compaction_summary',
    'delete_staging_snapshot',
    'finalize_compaction_artifacts',
    'maybe_update',
    'record_post_compact_baseline',
    'session_memory_exists',
]
