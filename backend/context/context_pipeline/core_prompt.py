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


class ContextPipelinePromptMixin:
    """ContextPipeline methods (mixin)."""

    def build_prompt_events(
        self,
        condensed_history: list[Event],
        *,
        state: State | None = None,
        llm_config: object | None = None,
        full_history: list[Event] | None = None,
    ) -> list[Event]:
        """Assemble LLM-facing events through layers 1–7."""
        history = full_history if full_history is not None else list(condensed_history)
        events = self._project_layers_1_to_3(
            history, state or _EmptyState(), apply_tool_budget=True
        )
        events = _drop_stale_prompt_state_artifacts(events)

        just_compacted = False
        if state is not None:
            pipe = state.extra_data.get('context_pipeline_state', {})
            just_compacted = bool(pipe.get(_JUST_COMPACTED_KEY))
            if just_compacted:
                pipe = dict(pipe)
                pipe[_JUST_COMPACTED_KEY] = False
                state.set_extra(
                    'context_pipeline_state', pipe, source='ContextPipeline'
                )

        packet = build_context_packet_observation(
            events,
            history,
            state=state,
            llm_config=llm_config,
            just_compacted=just_compacted,
        )
        if packet is not None:
            events = [packet, *events]

        window = select_prompt_events(
            events,
            llm_config,
            state=state,
            emergency_only=True,
            tool_budget_applied=True,
        )
        if (
            window.windowed
            and window.original_events >= DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS
            and window.selected_events < DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS
        ):
            logger.warning(
                'Emergency prompt window would collapse to %d/%d events; '
                'returning unwindowed prompt and marking critical memory pressure',
                window.selected_events,
                window.original_events,
            )
            if state is not None and hasattr(state, 'set_memory_pressure'):
                try:
                    state.set_memory_pressure('CRITICAL', source='ContextPipeline')
                except Exception:
                    logger.debug(
                        'Failed to mark emergency memory pressure', exc_info=True
                    )
            return events
        return window.events

    async def prewarm_compaction(self, state: State) -> Compaction | None:
        """Run 5b compaction off the hot path for foreground reuse."""
        if not self._config.allow_llm_hot_path:
            return None
        bind_session_context(state=state)
        history = list(getattr(state, 'history', []))
        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        if not events:
            return None
        llm_config = self._llm_config(state)
        budget = _cp.ContextBudget.from_events(events, llm_config=llm_config, state=state)
        action = await self._llm_structured_compaction(
            events, state, budget=budget, llm_config=llm_config
        )
        if action is None or not action.summary:
            return None
        return Compaction(action=action)

    def note_llm_step(self, state: State) -> None:
        """Reset condensation-loop counters after a real LLM step."""
        pipe = dict(state.extra_data.get('context_pipeline_state', {}))
        pipe[_CONSECUTIVE_CONDENSATION_KEY] = 0
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
