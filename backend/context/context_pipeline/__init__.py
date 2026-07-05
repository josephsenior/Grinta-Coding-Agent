"""Unified context compaction pipeline — one ordered path for every LLM step."""

from __future__ import annotations

from backend.context.compactor.compaction_finalizer import (
    finalize_compaction_artifacts,
)
from backend.context.compactor.pre_condensation_snapshot import delete_staging_snapshot
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    _synthetic_history_after_action,
)
from backend.context.context_pipeline.pipeline import ContextPipeline, _EmptyState
from backend.context.context_pipeline.types import (
    _JUST_COMPACTED_KEY,
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
    '_EmptyState',
    '_ContinuityGateDecision',
    '_JUST_COMPACTED_KEY',
    '_drop_stale_prompt_state_artifacts',
    '_synthetic_history_after_action',
    'build_compaction_summary',
    'delete_staging_snapshot',
    'finalize_compaction_artifacts',
    'maybe_update',
    'session_memory_exists',
]
