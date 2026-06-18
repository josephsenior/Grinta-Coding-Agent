"""Split submodule — see package facade for public API."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.canonical_state import (
    apply_canonical_patch,
    load_canonical_state,
    reduce_events_into_state,
    render_canonical_state_for_prompt,
    save_canonical_state,
    validate_canonical_state_for_compaction,
)
from backend.context.compaction.compact_boundary import project_after_compact_boundary
from backend.context.compaction.compaction_finalizer import finalize_compaction_artifacts
from backend.context.compactor.compactor import Compaction
from backend.context.compaction.condensed_history import CondensedHistory
from backend.context.context_budget import ContextBudget, record_post_compact_baseline
from backend.context.prompt.context_packet import (
    CONTEXT_PACKET_MARKER,
    build_context_packet_observation,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.context.compaction.microcompact import apply_microcompact
from backend.context.compaction.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    save_snapshot,
)
from backend.context.prompt.prompt_window import select_prompt_events
from backend.context.memory.session_context import bind_session_context
from backend.context.memory.session_memory import (
    build_compaction_summary,
    maybe_update,
    session_memory_exists,
)
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_COMPACT_MIN_PRUNED_EVENTS,
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
    DEFAULT_DEGRADED_COMPACT_TAIL_RATIO,
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS,
    DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS,
    DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
    DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    DEFAULT_PROMPT_MIN_TOOL_LOOPS,
)
from backend.core.logger import app_logger as logger
from backend.inference.capabilities.context_limits import limits_from_config
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event


from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    _latest_event_id,
    _pruned_ids,
    _projected_compaction_token_reduction,
    _select_compaction_tail,
    _shrink_tail_for_token_reduction,
    _synthetic_history_after_action,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.types import (
    PipelineStepResult,
    _COMPACTION_TARGET_RATIO,
    _ContinuityGateDecision,
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
)

import backend.context.context_pipeline as _cp

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State


class ContextPipelineStateMixin:
    """ContextPipeline methods (mixin)."""

    def _llm_cooldown_elapsed(self, state: State) -> bool:
        pipe = state.extra_data.get('context_pipeline_state', {})
        last = pipe.get(_LAST_LLM_COMPACT_KEY)
        if not isinstance(last, (int, float)):
            return True
        return (time.time() - last) >= self._llm_compact_cooldown

    def _record_llm_compact_attempt(self, state: State) -> None:
        pipe = dict(state.extra_data.get('context_pipeline_state', {}))
        pipe[_LAST_LLM_COMPACT_KEY] = time.time()
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _mark_just_compacted(self, state: State) -> None:
        pipe = dict(state.extra_data.get('context_pipeline_state', {}))
        pipe[_JUST_COMPACTED_KEY] = True
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _pipeline_state(self, state: State) -> dict[str, Any]:
        raw = state.extra_data.get('context_pipeline_state', {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _should_skip_compaction(self, state: State, *, force: bool) -> bool:
        if force:
            return False
        pipe = self._pipeline_state(state)
        if pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0) >= 2:
            return True
        last = pipe.get(_LAST_BOUNDARY_COMPACT_KEY)
        if isinstance(last, (int, float)):
            if (time.time() - last) < self._boundary_compact_cooldown:
                return True
        skip_until = pipe.get(_SKIP_COMPACTION_UNTIL_KEY)
        if isinstance(skip_until, int):
            history = list(getattr(state, 'history', []))
            latest_id = getattr(history[-1], 'id', None) if history else None
            if isinstance(latest_id, int) and latest_id < skip_until:
                return True
        ineffective_until = pipe.get(_INEFFECTIVE_COMPACT_UNTIL_KEY)
        if (
            isinstance(ineffective_until, (int, float))
            and time.time() < ineffective_until
        ):
            return True
        return False

    def _set_skip_compaction(self, state: State) -> None:
        apply_ineffective_compaction_backoff(state)

    def _clear_ineffective_compaction_backoff(self, state: State) -> None:
        pipe = self._pipeline_state(state)
        pipe.pop(_SKIP_COMPACTION_UNTIL_KEY, None)
        pipe.pop(_INEFFECTIVE_COMPACT_STREAK_KEY, None)
        pipe.pop(_INEFFECTIVE_COMPACT_UNTIL_KEY, None)
        pipe.pop(_CONTINUITY_REJECTION_FP_KEY, None)
        pipe.pop(_CONTINUITY_REJECTION_STREAK_KEY, None)
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _increment_condensation_counter(self, state: State) -> None:
        pipe = self._pipeline_state(state)
        count = pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0)
        if not isinstance(count, int):
            count = 0
        pipe[_CONSECUTIVE_CONDENSATION_KEY] = count + 1
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _record_boundary_compact(
        self,
        state: State,
        history: list[Event],
        action: CondensationAction,
    ) -> None:
        self._clear_ineffective_compaction_backoff(state)
        pipe = self._pipeline_state(state)
        pipe[_LAST_BOUNDARY_COMPACT_KEY] = time.time()
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
        post_events = project_after_compact_boundary(
            _synthetic_history_after_action(history, action)
        )
        record_post_compact_baseline(state, post_events)
