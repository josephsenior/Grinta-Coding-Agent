"""Split submodule — see package facade for public API."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.context.compactor.compact_boundary import project_after_compact_boundary
from backend.context.context_budget import record_post_compact_baseline
from backend.context.context_pipeline.core_base import ContextPipelineBaseMixin
from backend.context.context_pipeline.helpers import (
    _synthetic_history_after_action,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.types import (
    _CONSECUTIVE_CONDENSATION_KEY,
    _CONTINUITY_REJECTION_FP_KEY,
    _CONTINUITY_REJECTION_STREAK_KEY,
    _INEFFECTIVE_COMPACT_STREAK_KEY,
    _INEFFECTIVE_COMPACT_UNTIL_KEY,
    _JUST_COMPACTED_KEY,
    _LAST_BOUNDARY_COMPACT_KEY,
    _LAST_LLM_COMPACT_KEY,
    _SKIP_COMPACTION_UNTIL_KEY,
)
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


class ContextPipelineStateMixin(ContextPipelineBaseMixin):
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
